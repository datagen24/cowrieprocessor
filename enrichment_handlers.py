"""External enrichment handlers for Cowrie log analysis.

This module contains functions for enriching Cowrie log data with external
API data from VirusTotal, DShield, URLHaus, and SPUR.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List

import requests


def with_timeout(timeout_seconds: float, func, *args, **kwargs):
    """Execute a function with a timeout.
    
    Args:
        timeout_seconds: Maximum time to wait for the function
        func: Function to execute
        *args: Arguments to pass to the function
        **kwargs: Keyword arguments to pass to the function
        
    Returns:
        Result of the function call
        
    Raises:
        TimeoutError: If the function doesn't complete within the timeout
    """
    import signal
    
    def timeout_handler(signum, frame):
        raise TimeoutError("Operation timed out")
    
    # Set the signal handler
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(int(timeout_seconds))
    
    try:
        result = func(*args, **kwargs)
        return result
    finally:
        # Restore the old handler
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def vt_query(hash: str, cache_dir: Path, vtapi: str, skip_enrich: bool = False) -> None:
    """Query VirusTotal for a file hash and write the JSON response.
    
    Args:
        hash: SHA-256 string of the file to look up
        cache_dir: Directory to write/read cached VT responses
        vtapi: VirusTotal API key
        skip_enrich: If True, skip the API call
    """
    if skip_enrich or not vtapi:
        return
        
    vt_session = requests.session()
    vt_session.headers.update({'X-Apikey': vtapi})
    url = "https://www.virustotal.com/api/v3/files/" + hash
    
    try:
        response = vt_session.get(url, timeout=30)
        response.raise_for_status()
        
        vt_path = cache_dir / hash
        with open(vt_path, 'w', encoding='utf-8') as f:
            f.write(response.text)
    except Exception as e:
        logging.error(f"VT query failed for {hash}: {e}")
    finally:
        vt_session.close()


def dshield_query(ip_address: str, email: str, skip_enrich: bool = False) -> Dict[str, Any]:
    """Query DShield for information about an IP address.
    
    Args:
        ip_address: IP address string
        email: Email address for DShield API
        skip_enrich: If True, return empty data
        
    Returns:
        Parsed JSON response as a dictionary
    """
    if skip_enrich:
        return {"ip": {"asname": "", "ascountry": ""}}
        
    # Check cache
    cache_dir = Path('/mnt/dshield/data/cache')
    cache_file = cache_dir / f"dshield_{ip_address}.json"
    
    if cache_file.exists():
        try:
            with open(cache_file, 'r') as f:
                cached_data = json.load(f)
                if time.time() - cached_data.get('timestamp', 0) < 86400:  # 24 hours
                    return cached_data.get('data', {"ip": {"asname": "", "ascountry": ""}})
        except Exception:
            pass
    
    dshield_session = requests.session()
    url = f"https://dshield.org/api/ip/{ip_address}?email={email}"
    
    try:
        response = dshield_session.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        # Cache the result
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, 'w') as f:
                json.dump({'timestamp': time.time(), 'data': data}, f)
        except Exception:
            pass
            
        return data
    except Exception as e:
        logging.error(f"DShield query failed for {ip_address}: {e}")
        return {"ip": {"asname": "", "ascountry": ""}}
    finally:
        dshield_session.close()


def safe_read_uh_data(ip_address: str, urlhausapi: str, skip_enrich: bool = False) -> str:
    """Safely read URLHaus data with timeout handling.
    
    Args:
        ip_address: IP address to query
        urlhausapi: URLHaus API key
        skip_enrich: If True, return empty string
        
    Returns:
        Comma-separated string of unique URLHaus tags, or empty string
    """
    if skip_enrich:
        return ""
        
    try:
        return with_timeout(30, read_uh_data, ip_address, urlhausapi)
    except TimeoutError:
        logging.warning(f"URLHaus query timed out for IP {ip_address}")
        return "TIMEOUT"


def read_uh_data(ip_address: str, uh_api: str) -> str:
    """Read URLHaus data for an IP address.
    
    Args:
        ip_address: IP address string
        uh_api: URLHaus API key
        
    Returns:
        Comma-separated string of unique URLHaus tags, or empty string
    """
    cache_dir = Path('/mnt/dshield/data/cache')
    uh_path = cache_dir / ("uh_" + ip_address)
    
    if not uh_path.exists():
        uh_session = requests.session()
        uh_header = {'Auth-Key': uh_api}
        host = {'host': ip_address}
        
        try:
            response = uh_session.post('https://urlhaus-api.abuse.ch/v1/host/', 
                                     headers=uh_header, data=host, timeout=30)
            response.raise_for_status()
            
            with open(uh_path, 'w', encoding='utf-8') as f:
                f.write(response.text)
        except Exception as e:
            logging.error(f"URLHaus query failed for {ip_address}: {e}")
            return ""
        finally:
            uh_session.close()
    
    try:
        with open(uh_path, 'r', encoding='utf-8') as f:
            uh_data = f.readlines()
    except FileNotFoundError:
        return ""
    
    file_content = ""
    for eachline in uh_data:
        file_content += eachline
    
    try:
        json_data = json.loads(file_content)
        tags: set[str] = set()
        for eachurl in json_data['urls']:
            if eachurl['tags']:
                for eachtag in eachurl['tags']:
                    tags.add(eachtag)
        stringtags = ""
        for eachtag in tags:
            stringtags += eachtag + ", "
        return stringtags[:-2]
    except Exception:
        return ""


def read_spur_data(ip_address: str, spurapi: str, skip_enrich: bool = False) -> List[str]:
    """Read cached SPUR.us data and return normalized fields.
    
    Args:
        ip_address: IP address string
        spurapi: SPUR API key
        skip_enrich: If True, return empty data
        
    Returns:
        List of SPUR attributes in the following order:
        [asn, asn_org, organization, infrastructure, client_behaviors,
         client_proxies, client_types, client_count, client_concentration,
         client_countries, client_geo_spread, risks, services, location,
         tunnel_anonymous, tunnel_entries, tunnel_operator, tunnel_type]
    """
    if skip_enrich:
        return ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
        
    cache_dir = Path('/mnt/dshield/data/cache')
    spur_path = cache_dir / ("spur_" + ip_address.replace(":", "_") + ".json")
    
    if not spur_path.exists():
        spur_session = requests.session()
        spur_session.headers = {'Token': spurapi}
        
        try:
            response = spur_session.get(f"https://spur.us/api/v1/context/{ip_address}", timeout=30)
            response.raise_for_status()
            
            with open(spur_path, 'w', encoding='utf-8') as f:
                f.write(response.text)
        except Exception as e:
            logging.error(f"SPUR query failed for {ip_address}: {e}")
            return ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
        finally:
            spur_session.close()
    
    try:
        with open(spur_path, 'r', encoding='utf-8') as f:
            spur_data = f.readlines()
    except FileNotFoundError:
        return ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
    
    file_content = ""
    for eachline in spur_data:
        file_content += eachline
    
    try:
        json_data = json.loads(file_content)
    except Exception:
        return ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
    
    # Extract SPUR data fields
    spur_list = []
    
    # ASN data
    asn = json_data.get('asn', '')
    spur_list.append(str(asn))
    
    asn_org = json_data.get('asn_organization', '')
    spur_list.append(str(asn_org))
    
    organization = json_data.get('organization', '')
    spur_list.append(str(organization))
    
    infrastructure = json_data.get('infrastructure', '')
    spur_list.append(str(infrastructure))
    
    # Client data
    client_behaviors = json_data.get('client_behaviors', '')
    spur_list.append(str(client_behaviors))
    
    client_proxies = json_data.get('client_proxies', '')
    spur_list.append(str(client_proxies))
    
    client_types = json_data.get('client_types', '')
    spur_list.append(str(client_types))
    
    client_count = json_data.get('client_count', '')
    spur_list.append(str(client_count))
    
    client_concentration = json_data.get('client_concentration', '')
    spur_list.append(str(client_concentration))
    
    client_countries = json_data.get('client_countries', '')
    spur_list.append(str(client_countries))
    
    client_geo_spread = json_data.get('client_geo_spread', '')
    spur_list.append(str(client_geo_spread))
    
    # Risk and service data
    risks = json_data.get('risks', '')
    spur_list.append(str(risks))
    
    services = json_data.get('services', '')
    spur_list.append(str(services))
    
    location = json_data.get('location', '')
    spur_list.append(str(location))
    
    # Tunnel data
    tunnel_anonymous = ""
    tunnel_entries = ""
    tunnel_operator = ""
    tunnel_type = ""
    
    if "tunnels" in json_data:
        for each_tunnel in json_data['tunnels']:
            if "anonymous" in each_tunnel:
                tunnel_anonymous = each_tunnel['anonymous']
            if "entries" in each_tunnel:
                tunnel_entries = each_tunnel['entries']
            if "operator" in each_tunnel:
                tunnel_operator = each_tunnel['operator']
            if "type" in each_tunnel:
                tunnel_type = each_tunnel['type']
    
    spur_list.append(tunnel_anonymous)
    spur_list.append(tunnel_entries)
    spur_list.append(tunnel_operator)
    spur_list.append(tunnel_type)
    
    return spur_list

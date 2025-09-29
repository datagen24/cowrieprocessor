#!/usr/bin/bash

# Steven Peterson
# Date: $(date "+%Y-%m-%d")
# Version: 1.1

# This script automatically queries the IP list from ISC website and processes it for ELK ingestion.
# Original script by Guy Bruneau, adapted for SIEM environment

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="/var/log/iscipintel.log"
DEBUG=true  # Set to false to disable debug logging

# Ensure we have a log file
touch "$LOG_FILE"

log_message() {
    local level="$1"
    local message="$2"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${level}: $message" | tee -a "$LOG_FILE"
}

debug_message() {
    if [[ "$DEBUG" == "true" ]]; then
        log_message "DEBUG" "$1"
    fi
}

# Configuration
ISC_DIR="/mnt/dshield/aws-eastus-dshield/NSM/iscintel"
ISC_API_URL="https://isc.sans.edu/api/sources/attacks/5000"

# Function to check and create directory
check_create_dir() {
    local dir="$1"
    if [[ ! -d "$dir" ]]; then
        mkdir -p "$dir"
        log_message "INFO" "Directory '$dir' created"
    else
        debug_message "Directory '$dir' already exists"
    fi
}

main() {
    log_message "INFO" "Starting automated ISC IP intelligence collection"
    
    # Calculate dates
    YESTERDAY=$(date -d "1 day ago" '+%Y-%m-%d')
    TWO_DAYS_AGO=$(date -d "2 day ago" '+%Y-%m-%d')
    
    # Setup file paths
    local raw_file="$ISC_DIR/$YESTERDAY.json"
    local processed_file="$ISC_DIR/iscintel-$YESTERDAY.json"
    local old_file="$ISC_DIR/iscintel-$TWO_DAYS_AGO.json"
    
    # Check and create directory
    check_create_dir "$ISC_DIR"
    
    # Change to ISC directory
    cd "$ISC_DIR" || {
        log_message "ERROR" "Failed to change to directory $ISC_DIR"
        exit 1
    }
    
    # Download and process the data
    log_message "INFO" "Downloading ISC data for $YESTERDAY"
    if wget "$ISC_API_URL/$YESTERDAY?json" -O "$raw_file"; then
        log_message "INFO" "Successfully downloaded raw data"
        
        # Process the JSON file
        log_message "INFO" "Processing JSON data"
        if cat "$raw_file" | tr -d '[]' | sed 's/},{/}\n{/g' > "$processed_file"; then
            log_message "INFO" "Successfully processed JSON data"
            
            # Cleanup old files
            if [[ -f "$old_file" ]]; then
                rm -f "$old_file"
                log_message "INFO" "Removed old file: $old_file"
            fi
            
            # Cleanup raw file
            rm -f "$raw_file"
            log_message "INFO" "Cleaned up raw data file"
        else
            log_message "ERROR" "Failed to process JSON data"
            exit 1
        fi
    else
        log_message "ERROR" "Failed to download ISC data"
        exit 1
    fi
    
    log_message "INFO" "ISC IP intelligence collection completed"
}

# Run the main function
main

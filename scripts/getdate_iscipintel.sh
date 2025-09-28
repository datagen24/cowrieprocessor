#!/usr/bin/bash

# Steven Peterson
# Date: $(date "+%Y-%m-%d")
# Version: 1.2

# This script is used to backfill missing ISC IP intelligence data.
# It can be run manually to:
# 1. Check for missing dates in the output folder
# 2. Backfill data for specific dates
# Original script by Guy Bruneau, adapted for SIEM environment

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="/var/log/iscipintel_backfill.log"
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
ISC_DIR="/mnt/dshield/aws-eastus/NSM/iscintel"
ISC_API_URL="https://isc.sans.edu/api/sources/attacks/5000"
MAX_DAYS_BACK=30  # Maximum number of days to look back for missing data

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

# Function to validate date format
validate_date() {
    local date="$1"
    if ! [[ "$date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        return 1
    fi
    
    # Check if date is valid (e.g., not 2024-02-31)
    if ! date -d "$date" >/dev/null 2>&1; then
        return 1
    fi
    
    return 0
}

# Function to check if data exists for a date
check_data_exists() {
    local date="$1"
    local file="$ISC_DIR/iscintel-$date.json"
    if [[ -f "$file" ]]; then
        # Check if file is not empty and has valid JSON content
        if [[ -s "$file" ]] && jq empty "$file" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

# Function to process a single date
process_date() {
    local date="$1"
    local raw_file="$ISC_DIR/$date.json"
    local processed_file="$ISC_DIR/iscintel-$date.json"
    
    log_message "INFO" "Processing data for $date"
    
    # Download and process the data
    if wget "$ISC_API_URL/$date?json" -O "$raw_file"; then
        log_message "INFO" "Successfully downloaded raw data"
        
        # Process the JSON file
        if cat "$raw_file" | tr -d '[]' | sed 's/},{/}\n{/g' > "$processed_file"; then
            log_message "INFO" "Successfully processed JSON data"
            
            # Cleanup raw file
            rm -f "$raw_file"
            log_message "INFO" "Cleaned up raw data file"
            return 0
        else
            log_message "ERROR" "Failed to process JSON data"
            rm -f "$raw_file" "$processed_file"
            return 1
        fi
    else
        log_message "ERROR" "Failed to download ISC data"
        rm -f "$raw_file"
        return 1
    fi
}

# Function to find missing dates
find_missing_dates() {
    local start_date="$1"
    local end_date="$2"
    local missing_dates=()
    
    log_message "INFO" "Checking for missing dates between $start_date and $end_date"
    
    local current_date="$start_date"
    while [[ "$current_date" <= "$end_date" ]]; do
        if ! check_data_exists "$current_date"; then
            missing_dates+=("$current_date")
            log_message "INFO" "Missing data for $current_date"
        fi
        current_date=$(date -d "$current_date + 1 day" '+%Y-%m-%d')
    done
    
    echo "${missing_dates[@]}"
}

main() {
    log_message "INFO" "Starting ISC IP intelligence backfill process"
    
    # Check and create directory
    check_create_dir "$ISC_DIR"
    
    # Change to ISC directory
    cd "$ISC_DIR" || {
        log_message "ERROR" "Failed to change to directory $ISC_DIR"
        exit 1
    }
    
    # Get user input for mode
    echo "Select mode:"
    echo "1) Check for missing dates"
    echo "2) Backfill specific date"
    echo "3) Backfill date range"
    read -r mode
    
    case $mode in
        1)
            # Check for missing dates
            end_date=$(date '+%Y-%m-%d')
            start_date=$(date -d "$end_date - $MAX_DAYS_BACK days" '+%Y-%m-%d')
            missing_dates=($(find_missing_dates "$start_date" "$end_date"))
            
            if [[ ${#missing_dates[@]} -eq 0 ]]; then
                log_message "INFO" "No missing dates found in the last $MAX_DAYS_BACK days"
            else
                log_message "INFO" "Found ${#missing_dates[@]} missing dates:"
                printf '%s\n' "${missing_dates[@]}"
                
                echo "Would you like to backfill these dates? (y/n)"
                read -r response
                if [[ "$response" =~ ^[Yy]$ ]]; then
                    for date in "${missing_dates[@]}"; do
                        process_date "$date"
                    done
                fi
            fi
            ;;
            
        2)
            # Backfill specific date
            echo "Enter the date to backfill (YYYY-MM-DD):"
            read -r date
            
            if ! validate_date "$date"; then
                log_message "ERROR" "Invalid date format. Please use YYYY-MM-DD"
                exit 1
            fi
            
            process_date "$date"
            ;;
            
        3)
            # Backfill date range
            echo "Enter start date (YYYY-MM-DD):"
            read -r start_date
            echo "Enter end date (YYYY-MM-DD):"
            read -r end_date
            
            if ! validate_date "$start_date" || ! validate_date "$end_date"; then
                log_message "ERROR" "Invalid date format. Please use YYYY-MM-DD"
                exit 1
            fi
            
            if [[ "$start_date" > "$end_date" ]]; then
                log_message "ERROR" "Start date must be before end date"
                exit 1
            fi
            
            missing_dates=($(find_missing_dates "$start_date" "$end_date"))
            
            if [[ ${#missing_dates[@]} -eq 0 ]]; then
                log_message "INFO" "No missing dates found in the specified range"
            else
                log_message "INFO" "Found ${#missing_dates[@]} missing dates:"
                printf '%s\n' "${missing_dates[@]}"
                
                echo "Would you like to backfill these dates? (y/n)"
                read -r response
                if [[ "$response" =~ ^[Yy]$ ]]; then
                    for date in "${missing_dates[@]}"; do
                        process_date "$date"
                    done
                fi
            fi
            ;;
            
        *)
            log_message "ERROR" "Invalid mode selected"
            exit 1
            ;;
    esac
    
    log_message "INFO" "ISC IP intelligence backfill process completed"
}

# Run the main function
main

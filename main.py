import json
import yaml
import logging
import argparse
import requests
from datetime import datetime, timedelta, timezone
import urllib.parse
from pathlib import Path
from typing import Dict
from copy import deepcopy
import shutil


logging.basicConfig(level=logging.INFO)

def format_datetime(date: datetime):
    return date.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# load token from file
with open("PERSONAL_ACCESS_TOKEN.txt") as f:
    TOKEN = f.readline().strip()

def load_config(config_file: str) -> Dict:
    config_path = Path(config_file) 
    if config_path.exists():
        with open(config_file) as f:
            try:
                config = yaml.safe_load(f)
                logging.info(f"Config file '{config_file}' loaded successfully.")
                return config
            except yaml.YAMLError as e:
                logging.exception(f"Config file: '{config_file}' probably corrupted or not in correct format")
                raise
    else:
        logging.info("Config file not found, creating with default config...")
        now_timestamp = datetime.now()
        yesterday_timestamp = now_timestamp - timedelta(days=1)
        default_config = {
            "last_queried": {
                "created_from": format_datetime(datetime(year=1900, month=1, day=1, tzinfo=timezone.utc)),
                "created_to": format_datetime(yesterday_timestamp),
            } 
        }
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as f:
            yaml.dump(default_config, f)

        return default_config
        
def main(config: Dict):
    url = "https://api.github.com/search/issues"
    new_config = deepcopy(config)

    session = requests.Session()

    session.headers.update(
        {
            'Authorization': f'Bearer {TOKEN}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28'
        }
    )
    
    now_timestamp = format_datetime(datetime.now())

    search_query_params = {
        "q": f"windows label:bug language:python state:open is:issue created:{config['last_queried']['created_to']}..{now_timestamp}",
        "sort": "created",
        "order": "asc",
        "page": 1
    }

    ## Updating the new query time duration for next run
    new_config["last_queried"]["created_to"] = now_timestamp
    new_config["last_queried"]["created_from"] = config['last_queried']['created_to']
    
    # search_query = f"windows+label:bug+language:python+state:open+is:issue&sort=created&order=asc&created:>{config['last_queried']['created_to']}&created:<{now_timestamp}"

    total_count = 0
    count_so_far = 0
    page = 1
    set_of_users = set()
    
    while True:
        search_query_params["page"] = page
        search_url_params = urllib.parse.urlencode(search_query_params)
        search_results = None
        for retry_number, timeout in enumerate([8, 16, 32, 128]):
            try:
                response = session.get(f'{url}?{search_url_params}', timeout=timeout)
                
                if response.status_code == 200:
                    search_results = response.json()
                    break
                elif response.status_code == 304:
                    raise RuntimeError(f"Response Status Code {response.status_code}: Not modified: Probably some issue on the server side")
                elif response.status_code == 403:
                    raise RuntimeError(f"Response Status Code {response.status_code}: Forbidden, probably the authentication token is incorrect or expired")
                elif response.status_code == 422:
                    raise RuntimeError(f"Response Status Code {response.status_code}: Wrong query format or the endpoint has been spammed")
                elif response.status_code == 503:
                    raise RuntimeError(f"Response Status Code {response.status_code}: Service is unavailable, probably the server is down")
            except requests.Timeout as e:
                logging.warning(f"Retry number: {retry_number}: Request {url}?{search_url_params} has timed out for {timeout} secs, trying again until retry count limit is reached.")
                continue
            except requests.ConnectionError as e:
                logging.error(f"Retry number: {retry_number}: Cannot connect to the URL: {url}?{search_query_params}, trying again until retry count limit is reached.")
                continue
            except requests.RequestException as e:
                logging.exception("A requests exception has occured")
                raise

        total_count = search_results["total_count"]
        set_of_users.update([item["user"]["login"] for item in search_results["items"]]) 

        count_so_far += len(search_results["items"])

        logging.info(f"Page {page}: Items received so far: {count_so_far} / {total_count}")
        logging.info(f"Page {page}: Number of users so far: {len(set_of_users)}")

        if count_so_far == total_count:
            break
            
        page += 1

    
    print(set_of_users)
    return new_config

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-file", required=True, help="path to the configuration file for the computation")

    args = parser.parse_args()

    config = load_config(args.config_file)

    new_config = main(config)

    config_path = Path(args.config_file)
    config_backup_path = config_path.with_name(f"{config_path.name}.backup")

    shutil.copy2(config_path, config_backup_path)
    logging.info(f"Backed up the existing config before overwriting: {config_path} -> {config_backup_path} ")

    with open(config_path, "w") as f:
        yaml.dump(new_config, f)
        logging.info(f"Successfully updated the config '{config_path}' with new values.")

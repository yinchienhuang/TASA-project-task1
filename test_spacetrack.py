#!/usr/bin/env python3
"""Test Space-Track API using official login method."""
import os
import sys
import requests
import json

# Load env
from pathlib import Path
env_file = Path(__file__).parent / '.env'
if env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(env_file)

username = os.environ.get("SPACETRACK_USERNAME", "").strip()
password = os.environ.get("SPACETRACK_PASSWORD", "").strip()

print(f"Testing Space-Track with username: {username}\n")

if not username or not password:
    print("ERROR: Credentials not found in .env")
    sys.exit(1)

try:
    with requests.Session() as session:
        # Step 1: Login using official endpoint
        print("Step 1: Logging into Space-Track...")
        login_url = "https://www.space-track.org/ajaxauth/login"
        login_data = {
            "identity": username,
            "password": password,
        }

        resp = session.post(login_url, data=login_data, timeout=10)
        print(f"  Status: {resp.status_code}")

        if resp.status_code != 200:
            print("[FAIL] Login failed")
            print(f"  Response: {resp.text[:200]}")
            sys.exit(1)

        print("[OK] Logged in successfully\n")

        # Step 2: Query TLE to verify session
        print("Step 2: Testing TLE query...")
        tle_url = (
            "https://www.space-track.org/basicspacedata/query"
            "/class/tle_latest"
            "/NORAD_CAT_ID/39084"
            "/orderby/EPOCH%20desc"
            "/limit/1"
            "/format/json"
        )

        print(f"  URL: {tle_url[:80]}...\n")
        resp = session.get(tle_url, timeout=10)
        print(f"  Status: {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            if data:
                print("[OK] Retrieved TLE data")
                tle = data[0]
                print(f"      NORAD: {tle.get('NORAD_CAT_ID')}")
                print(f"      Epoch: {tle.get('EPOCH')}\n")

                # Step 3: Query conjunctions
                print("Step 3: Fetching conjunctions...")
                conj_url = (
                    "https://www.space-track.org/basicspacedata/query"
                    "/class/conjunction"
                    "/NORAD_CAT_ID/39084"
                    "/orderby/TCA%20asc"
                    "/limit/10"
                    "/format/json"
                )

                print(f"  URL: {conj_url[:80]}...\n")
                resp = session.get(conj_url, timeout=10)
                print(f"  Status: {resp.status_code}")

                if resp.status_code == 200:
                    conjunctions = resp.json()
                    if conjunctions:
                        print(f"[OK] Found {len(conjunctions)} upcoming conjunctions for ISS\n")
                        for i, conj in enumerate(conjunctions[:3]):
                            print(f"Conjunction {i+1}:")
                            print(f"  TCA: {conj.get('TCA')}")
                            print(f"  Other NORAD: {conj.get('OTHER_NORAD_CAT_ID')}")
                            print(f"  Min range: {conj.get('MIN_RANGE_KM')} km\n")
                    else:
                        print("[OK] No conjunctions found (normal if ISS in quiet period)")
                else:
                    print(f"[FAIL] Status {resp.status_code}")
                    print(f"Response: {resp.text[:200]}")
            else:
                print("[FAIL] Empty TLE response")
        else:
            print(f"[FAIL] Status {resp.status_code}")
            print(f"Response: {resp.text[:200]}")

except Exception as e:
    print(f"[ERROR] {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

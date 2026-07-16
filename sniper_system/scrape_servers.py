import requests
import time

PLACE_ID = 2788229376

def scrape_all_servers():
    servers = []
    cursor = None
    page = 1

    while True:
        url = f"https://games.roblox.com/v1/games/{PLACE_ID}/servers/Public?sortOrder=Asc&limit=100"
        if cursor:
            url += f"&cursor={cursor}"

        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 429:
                print(f"rate limited, waiting 5s...")
                time.sleep(5)
                continue
            if r.status_code != 200:
                print(f"error {r.status_code} on page {page}")
                break
            data = r.json()
        except Exception as e:
            print(f"request failed: {e}")
            break

        batch = data.get("data", [])
        for s in batch:
            if "id" in s:
                servers.append(s["id"])

        print(f"page {page} — got {len(batch)} servers (total: {len(servers)})")

        cursor = data.get("nextPageCursor")
        if not cursor:
            print("no more pages")
            break

        page += 1
        time.sleep(0.3)  # be polite, avoid rate limit

    return servers

if __name__ == "__main__":
    print(f"scraping servers for place {PLACE_ID}...")
    servers = scrape_all_servers()
    print(f"\ndone — {len(servers)} servers found")

    with open("servers.txt", "w") as f:
        for s in servers:
            f.write(s + "\n")

    print("saved to servers.txt")

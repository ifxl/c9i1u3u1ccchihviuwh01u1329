import requests
import time
import sys

# ── config ────────────────────────────────────────────────────
# paste the user ID of whoever's friends list you want to scrape
TARGET_USER_ID = 0  # <-- put user ID here, or pass as CLI arg

OUTPUT_FILE = "friend_ids.txt"
# ─────────────────────────────────────────────────────────────

def get_username(user_id):
    try:
        r = requests.post(
            "https://users.roblox.com/v1/users",
            json={"userIds": [int(user_id)], "excludeBannedUsers": False},
            timeout=10
        )
        d = r.json().get("data", [])
        if d:
            return d[0].get("name", str(user_id))
    except:
        pass
    return str(user_id)

def scrape_friends(user_id):
    friends = []
    cursor = ""
    page = 1

    while True:
        url = f"https://friends.roblox.com/v1/users/{user_id}/friends?cursor={cursor}&limit=100"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 429:
                print("rate limited, waiting 5s...")
                time.sleep(5)
                continue
            if r.status_code == 400:
                print(f"[!] User {user_id} has private friends list or doesn't exist")
                break
            if r.status_code != 200:
                print(f"[!] HTTP {r.status_code} on page {page}")
                break

            data = r.json()
            batch = data.get("data", [])

            for friend in batch:
                friends.append({
                    "id":       friend["id"],
                    "username": friend["name"],
                    "display":  friend.get("displayName", friend["name"])
                })

            print(f"  page {page} — {len(batch)} friends (total: {len(friends)})")

            # friends API doesn't paginate with cursor — it returns all at once
            # but handle cursor just in case
            cursor = data.get("nextPageCursor") or ""
            if not cursor:
                break

            page += 1
            time.sleep(0.3)

        except Exception as e:
            print(f"[!] Request failed: {e}")
            break

    return friends

def main():
    user_id = TARGET_USER_ID

    # allow passing user ID as command line arg
    if len(sys.argv) > 1:
        try:
            user_id = int(sys.argv[1])
        except ValueError:
            print(f"[!] Invalid user ID: {sys.argv[1]}")
            sys.exit(1)

    if user_id == 0:
        user_id = int(input("Enter Roblox user ID: ").strip())

    print(f"\nscraping friends for user ID: {user_id}")
    username = get_username(user_id)
    print(f"username: {username}\n")

    friends = scrape_friends(user_id)

    if not friends:
        print("[!] No friends found (private list or no friends)")
        return

    print(f"\n✓ found {len(friends)} friends")

    # save just the IDs
    with open(OUTPUT_FILE, "w") as f:
        for friend in friends:
            f.write(str(friend["id"]) + "\n")

    # also save a detailed version
    detail_file = OUTPUT_FILE.replace(".txt", "_detailed.txt")
    with open(detail_file, "w") as f:
        f.write(f"Friends of {username} ({user_id})\n")
        f.write(f"Total: {len(friends)}\n")
        f.write("-" * 40 + "\n")
        for friend in friends:
            f.write(f"{friend['id']} | {friend['username']} ({friend['display']})\n")

    print(f"IDs saved to:      {OUTPUT_FILE}")
    print(f"Details saved to:  {detail_file}")

    # print all IDs to console too
    print("\n── friend IDs ──")
    for friend in friends:
        print(f"  {friend['id']}  {friend['username']}")

if __name__ == "__main__":
    main()

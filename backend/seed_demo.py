"""Fill a running local server with demo data:  python seed_demo.py [http://127.0.0.1:8000]"""
import json
import sys
import urllib.request
from datetime import date, datetime, timedelta

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def post(path, body):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))


mom, dad, kid = (post("/api/members", {"name": n})["id"] for n in ("Mom", "Dad", "Mia"))
mon = date.today() - timedelta(days=date.today().weekday())


def ev(title, day, h, m=0, dur=1, who=None, all_day=False, loc="", repeat="none"):
    s = datetime.combine(mon + timedelta(days=day), datetime.min.time()).replace(hour=h, minute=m)
    e = s + timedelta(hours=dur)
    if all_day:
        s, e = s.replace(hour=0), s.replace(hour=23, minute=59)
    post("/api/events", {"title": title, "start": s.isoformat(), "end": e.isoformat(), "all_day": all_day,
                         "member_id": who, "location": loc, "repeat": repeat})


ev("School drop-off", 0, 8, 15, 1, kid); ev("Team standup", 0, 10, 0, 1, dad)
ev("Dentist", 1, 15, 30, 1, mom, loc="Smile Dental"); ev("Soccer practice", 2, 17, 0, 2, kid, loc="Riverside Park")
ev("Parent-teacher night", 3, 18, 30, 1, mom); ev("Date night", 4, 19, 0, 3, None)
ev("Grandma visits", 5, 0, all_day=True); ev("Birthday party", 5, 14, 0, 3, kid)
ev("Farmers market", 6, 9, 0, 2, mom, repeat="weekly"); ev("Trash day", 1, 0, all_day=True, repeat="weekly")
ev("Mia's birthday", 3, 0, all_day=True, who=kid, repeat="yearly"); ev("Vitamins", 0, 7, 30, 0, repeat="daily")
post("/api/chores", {"title": "Empty dishwasher", "member_id": kid, "due": date.today().isoformat(), "repeat": "daily"})
post("/api/chores", {"title": "Take out trash", "member_id": dad, "due": (date.today() + timedelta(days=1)).isoformat(), "repeat": "weekly"})
post("/api/chores", {"title": "Laundry", "member_id": mom, "due": (date.today() - timedelta(days=1)).isoformat()})
post("/api/chores", {"title": "Water plants"})
print("seeded")

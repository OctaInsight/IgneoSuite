"""In-memory stand-in for the octa_user_* database functions (tests only)."""
import hashlib
import secrets as pysecrets
import time
import uuid

APPS = [
    dict(id="igneosuite", family="science", name="IgneoSuite", description="Gaps in igneous data", icon="🪨",
         url="https://igneosuite.streamlit.app/", status="live", access_mode="open", group_label="Geoscience"),
    dict(id="explain_earth", family="science", name="ExplainEarth", description="Explaining Earth", icon="🌍",
         url="", status="construction", access_mode="open", group_label="Geoscience"),
    dict(id="octa_kpi", family="cloudearthi", name="Objectives & Work Plan Designer", description="KPIs", icon="📊",
         url="https://octakpi.streamlit.app/", status="live", access_mode="approval", group_label="Proposal Suite"),
    dict(id="octa_hours", family="cloudearthi", name="Working Hours", description="Hours", icon="⏱️",
         url="https://working-hours.streamlit.app", status="live", access_mode="approval", group_label="People"),
    dict(id="octa_game_1", family="games", name="Octa game", description="Soon", icon="🎮", url="",
         status="construction", access_mode="open", group_label="Games"),
]
H = lambda s: hashlib.sha256((s or "").encode()).hexdigest()  # noqa: E731


class FakeDB:
    def __init__(self):
        self.users, self.sessions, self.resets, self.access, self.usage, self.mails = {}, {}, {}, {}, [], []

    # helpers
    def _pub(self, uid):
        u = dict(self.users[uid])
        u.pop("pw")
        u["apps"] = sorted(a["id"] for a in APPS if (a["access_mode"] == "open" and self.access.get((uid, a["id"])) != "revoked")
                           or self.access.get((uid, a["id"])) == "granted")
        return u

    def _uid(self, tok):
        s = self.sessions.get(H(tok))
        return s["uid"] if s and s["exp"] > time.time() else None

    def _new_session(self, uid):
        t = pysecrets.token_hex(32)
        self.sessions[H(t)] = dict(uid=uid, exp=time.time() + 3 * 3600)
        return t

    def add_user(self, email, username, pw, **kw):
        uid = str(uuid.uuid4())
        self.users[uid] = dict(id=uid, email=email.lower(), username=username, pw=pw, role=kw.pop("role", "user"),
                               status="active", force_password_change=False, profiles={}, **kw)
        return uid

    # API
    def __call__(self, fn, timeout=20, **a):
        return getattr(self, fn.replace("octa_user_", ""))(**a)

    def register(self, p):
        if any(u["email"] == p["email"].lower() for u in self.users.values()):
            return dict(ok=False, error="This email is already registered.")
        if any(u["username"].lower() == p["username"].lower() for u in self.users.values()):
            return dict(ok=False, error="This username is taken. Please choose another.")
        keep = {k: p.get(k) for k in ("first_name", "last_name", "affiliation", "country", "job_title", "orcid",
                                       "website", "biography")}
        uid = self.add_user(p["email"], p["username"], p["password"], **keep)
        self.users[uid]["profiles"] = {p.get("family", "science"): p.get("profile", {})}
        app = next((x for x in APPS if x["id"] == p.get("app")), None)
        if app and app["access_mode"] == "approval":
            self.access[(uid, app["id"])] = "requested"
        return dict(ok=True, token=self._new_session(uid), user=self._pub(uid))

    def login(self, p_login, p_password, p_app):
        for uid, u in self.users.items():
            if p_login.lower() in (u["email"], u["username"].lower()) and u["pw"] == p_password:
                self.usage.append((uid, p_app, "login"))
                return dict(ok=True, token=self._new_session(uid), user=self._pub(uid))
        return dict(ok=False, error="Wrong email/username or password.")

    def session(self, p_token, p_app):
        uid = self._uid(p_token)
        if not uid:
            return dict(ok=False, error="Your session has ended. Please log in again.")
        self.sessions[H(p_token)]["exp"] = time.time() + 3 * 3600
        if p_app:
            self.usage.append((uid, p_app, "active"))
        return dict(ok=True, user=self._pub(uid))

    def logout(self, p_token, p_app):
        self.sessions.pop(H(p_token), None)

    def catalogue(self, p_token):
        uid = self._uid(p_token)
        mine = self._pub(uid)["apps"] if uid else []
        uses = lambda i: sum(1 for x in self.usage if x[0] == uid and x[1] == i)  # noqa: E731
        fam = {f: sum(uses(a["id"]) for a in APPS if a["family"] == f) for f in ("cloudearthi", "science", "games")}
        order = sorted(fam, key=lambda f: (-fam[f], ["cloudearthi", "science", "games"].index(f)))
        return dict(signed_in=bool(uid), family_order=order,
                    apps=[dict(a, can_open=a["id"] in mine, uses=uses(a["id"]),
                               requested=self.access.get((uid, a["id"])) == "requested") for a in APPS])

    def request_access(self, p_token, p_app):
        uid = self._uid(p_token)
        self.access[(uid, p_app)] = "requested"
        return dict(ok=True, status="requested")

    def update_profile(self, p_token, p):
        uid = self._uid(p_token)
        for k, v in p.items():
            if k not in ("family", "profile"):
                self.users[uid][k] = v
        self.users[uid]["profiles"].setdefault(p.get("family"), {}).update(p.get("profile", {}))
        return dict(ok=True, user=self._pub(uid))

    def change_password(self, p_token, p_old, p_new):
        uid = self._uid(p_token)
        if self.users[uid]["pw"] != p_old:
            return dict(ok=False, error="The current password is wrong.")
        self.users[uid].update(pw=p_new, force_password_change=False)
        return dict(ok=True)

    def reset_request(self, p_server_key, p_email, p_app):
        if p_server_key != "test-server-key":
            return dict(ok=False, error="not allowed")
        u = next((u for u in self.users.values() if u["email"] == p_email.lower()), None)
        if not u:
            return dict(ok=True, exists=False)
        t = pysecrets.token_hex(32)
        self.resets[H(t)] = dict(uid=u["id"], used=False, app=p_app)
        return dict(ok=True, exists=True, token=t, username=u["username"], first_name=u.get("first_name"), email=u["email"])

    def reset_check(self, p_token):
        r = self.resets.get(H(p_token))
        if not r or r["used"]:
            return dict(ok=False, error="This link has expired or was already used. Please ask for a new one.")
        u = self.users[r["uid"]]
        return dict(ok=True, username=u["username"], email=u["email"], return_app=r["app"])

    def reset_complete(self, p_token, p_new_password, p_new_username):
        r = self.resets.get(H(p_token))
        if not r or r["used"]:
            return dict(ok=False, error="This link has expired or was already used. Please ask for a new one.")
        u = self.users[r["uid"]]
        u["pw"] = p_new_password
        if p_new_username:
            u["username"] = p_new_username
        r["used"] = True
        self.sessions = {k: v for k, v in self.sessions.items() if v["uid"] != u["id"]}
        return dict(ok=True, username=u["username"], return_app=r["app"])

    def admin(self, p_token, p):
        uid = self._uid(p_token)
        if not uid or self.users[uid]["role"] != "admin":
            return dict(ok=False, error="Admins only.")
        if p["action"] == "list_requests":
            return dict(ok=True, requests=[dict(user_id=k[0], app_id=k[1], email=self.users[k[0]]["email"],
                                                name=self.users[k[0]].get("first_name") or "", affiliation=None,
                                                app=next(a["name"] for a in APPS if a["id"] == k[1]))
                                           for k, v in self.access.items() if v == "requested"])
        if p["action"] == "list_users":
            return dict(ok=True, users=[dict(user_id=u["id"], email=u["email"], username=u["username"],
                                             name=u.get("first_name") or "", affiliation=u.get("affiliation"),
                                             status=u["status"], role=u["role"], last_login_at=None,
                                             apps=self._pub(u["id"])["apps"]) for u in self.users.values()])
        if p["action"] == "set_access":
            self.access[(p["user_id"], p["app_id"])] = p["status"]
            return dict(ok=True)
        if p["action"] == "set_status":
            self.users[p["user_id"]]["status"] = p["status"]
            return dict(ok=True)


DB = FakeDB()


def install():
    """Patch octa_auth to use the fake database and record emails instead of sending them."""
    import octa_auth.client as c
    import octa_auth.mail as m
    c.rpc = DB
    m.send = lambda to, subject, paragraphs, button=None, after=None: DB.mails.append(
        dict(to=to, subject=subject, text=" ".join(paragraphs), link=button[1] if button else None))
    m.enabled = lambda: True
    return DB

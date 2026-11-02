# Octa Insight portal (planned)

IgneoSuite is built to run on its own today and to be embedded in the Octa Insight portal later.

The contract between the portal and any Octa Insight app is two objects in the app's `ui` module:

* `APP_META` – id, name, tagline, version (used for the app catalogue).
* `render(user=None)` – draws the app; the portal passes the signed-in user (or `None` for open use).

Planned portal layer (not built yet):

* Supabase Auth for sign-up, login, username and password reset (email links).
* Supabase tables: `profiles` (user id, username, organisation), `apps` (id, name, section, tagline),
  `subscriptions` (user id, app id, status, start, end), `usage` (user id, app id, timestamp).
* App catalogue in three sections; the order of sections and apps follows each user's `usage` counts.
* Secrets (Supabase URL and anon key) go in `.streamlit/secrets.toml`, which is never committed.

Section names are still to be decided.

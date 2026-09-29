"""Zoneflow private login (single admin, no signup).

Architecture (see deployment/README.md):

    Internet --HTTPS 443--> Caddy --forward_auth--> login service (server.py, 127.0.0.1:8601)
                              |                        sets an HttpOnly session cookie after login
                              +--reverse_proxy--> Streamlit (127.0.0.1:8501)
                                                     gate.py re-checks the session on every rerun

Secrets come only from the server environment / a private env file (config.py), never from Git or the browser.
"""

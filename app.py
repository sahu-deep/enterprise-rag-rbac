import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.request import urlopen
import streamlit as st

import requests

API_BASE_URL = "http://127.0.0.1:8000"

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"

# Make the local module importable when the script is launched directly.
sys.path.insert(0, str(APP_DIR))

from codebasic_chat import sanitize_pii
from rbac import (
    ASSIGNABLE_ROLES,
    can_access_collection,
    get_available_collections,
    get_role_label,
)


def launch_streamlit_app() -> None:
    port = os.getenv("PORT", "8501")
    url = f"http://127.0.0.1:{port}"

    try:
        with urlopen(url, timeout=2):
            webbrowser.open(url)
            print(f"Streamlit already running at {url}")
            return
    except Exception:
        pass

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP_DIR / "app.py"),
        "--server.port",
        str(port),
        "--server.headless",
        "true",
    ]
    env = os.environ.copy()
    env["STREAMLIT_LAUNCHED"] = "1"

    subprocess.Popen(
        cmd,
        cwd=str(APP_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )
    time.sleep(5)
    webbrowser.open(url)
    print(f"Opening {url} in your browser...")


def run_streamlit_ui() -> None:
    st.set_page_config(page_title="Departmental Knowledge Assistant", page_icon="💬", layout="wide")
    st.markdown(
        """
        <style>
        :root {
            --brand-blue: #4263eb;
            --brand-violet: #7555d9;
            --ink: #252943;
            --muted-ink: #687087;
            --line: rgba(82, 97, 145, .16);
        }
        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(ellipse at 85% 0%, rgba(117, 85, 217, .07), transparent 32rem),
                #fbfcff;
            color: var(--ink);
        }
        [data-testid="stMainBlockContainer"] {
            max-width: 1120px;
            padding-top: 3rem;
            padding-bottom: 3rem;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #f1f4ff 0%, #f7f8fc 100%);
            border-right: 1px solid var(--line);
        }
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
            color: var(--muted-ink);
        }
        .app-hero {
            position: relative;
            overflow: hidden;
            padding: 2rem 2.2rem;
            margin-bottom: 1.6rem;
            border: 1px solid rgba(94, 105, 170, .17);
            border-radius: 22px;
            background: linear-gradient(120deg, #ffffff 15%, #f4f5ff 100%);
            box-shadow: 0 16px 45px rgba(50, 61, 112, .08);
        }
        .app-hero::before {
            position: absolute;
            inset: 0 auto 0 0;
            width: 4px;
            background: linear-gradient(180deg, var(--brand-blue), var(--brand-violet));
            content: "";
        }
        .app-hero::after {
            position: absolute;
            top: -4rem;
            right: -2rem;
            width: 14rem;
            height: 14rem;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(117, 85, 217, .13), transparent 70%);
            content: "";
            pointer-events: none;
        }
        .app-eyebrow {
            color: var(--brand-blue);
            font-size: .76rem;
            font-weight: 700;
            letter-spacing: .16em;
            text-transform: uppercase;
        }
        .app-hero h1 {
            margin: .55rem 0 .5rem;
            color: var(--ink);
            font-size: clamp(2rem, 4vw, 3rem);
        }
        .app-hero p { margin: 0; color: var(--muted-ink); font-size: 1.02rem; }
        [data-testid="stForm"] {
            padding: 1.25rem;
            border: 1px solid var(--line);
            border-radius: 16px;
            background: rgba(255, 255, 255, .82);
            box-shadow: 0 10px 30px rgba(50, 61, 112, .045);
        }
        [data-testid="stTextInput"] input,
        [data-testid="stSelectbox"] > div > div {
            border-radius: 10px;
        }
        [data-testid="stTextInput"] input:focus,
        [data-testid="stSelectbox"] > div > div:focus-within {
            border-color: var(--brand-blue);
            box-shadow: 0 0 0 3px rgba(66, 99, 235, .12);
        }
        .stButton > button, [data-testid="stFormSubmitButton"] > button {
            border-radius: 10px;
            font-weight: 650;
            transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease;
        }
        [data-testid="stFormSubmitButton"] > button {
            border: 0;
            background: linear-gradient(110deg, var(--brand-blue), var(--brand-violet));
            color: #fff;
            box-shadow: 0 6px 16px rgba(84, 88, 205, .2);
        }
        [data-testid="stFormSubmitButton"] > button:hover {
            border: 0;
            background: linear-gradient(110deg, #3454d1, #6544c6);
            color: #fff;
            box-shadow: 0 8px 20px rgba(84, 88, 205, .28);
        }
        .stButton > button:hover {
            transform: translateY(-1px);
            border-color: var(--brand-blue);
            box-shadow: 0 5px 14px rgba(66, 99, 235, .12);
        }
        [data-testid="stChatMessage"] {
            border: 1px solid var(--line);
            border-radius: 16px;
            background: rgba(255, 255, 255, .84);
            box-shadow: 0 5px 18px rgba(50, 61, 112, .035);
        }
        [data-testid="stChatInput"] textarea {
            border: 1px solid rgba(82, 97, 145, .22);
            border-radius: 14px;
            background: #fff;
            box-shadow: 0 8px 26px rgba(50, 61, 112, .08);
        }
        [data-testid="stChatInput"] textarea:focus {
            border-color: var(--brand-blue);
            box-shadow: 0 0 0 3px rgba(66, 99, 235, .12);
        }
        [data-testid="stChatInput"] button {
            border: 0;
            border-radius: 10px;
            background: linear-gradient(110deg, var(--brand-blue), var(--brand-violet));
            color: #fff;
        }
        [data-testid="stChatInput"] button:hover {
            background: linear-gradient(110deg, #3454d1, #6544c6);
            color: #fff;
        }
        [data-testid="stAlert"] {
            border: 1px solid rgba(66, 99, 235, .15);
            border-left: 3px solid var(--brand-blue);
            border-radius: 12px;
            background: #f0f4ff;
        }
        .sidebar-brand {
            padding: .5rem 0 1.1rem;
            font-weight: 700;
            font-size: 1.05rem;
        }
        .sidebar-brand span { color: var(--brand-blue); }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "user" not in st.session_state:
        st.session_state.user = None
    if "token" not in st.session_state:
        st.session_state.token = None

    st.markdown(
        """
        <div class="app-hero">
            <div class="app-eyebrow">Private knowledge · Clear answers</div>
            <h1>💬 Departmental Knowledge Assistant</h1>
            <p>Get grounded answers from the knowledge sources your role is allowed to access.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.sidebar.markdown('<div class="sidebar-brand">💬 <span>Knowledge</span> Workspace</div>', unsafe_allow_html=True)

    if st.session_state.user is None:
        try:
            status_response = requests.get(
                f"{API_BASE_URL}/setup/status",
                timeout=10,
            )
            status_response.raise_for_status()
            setup_required = status_response.json()["setup_required"]
        except requests.RequestException:
            st.error("Unable to connect to the API. Ensure FastAPI is running.")
            return

        if setup_required:
            setup_col, _ = st.columns([1.15, 1])
            with setup_col:
                st.subheader("Set up your workspace")
                st.write("Create the administrator account to get started. You can add department users afterward.")
                with st.form("initial_admin_form"):
                    username = st.text_input("Administrator username")
                    full_name = st.text_input("Administrator full name")
                    password = st.text_input("Password (at least 12 characters)", type="password")
                    password_confirmation = st.text_input("Confirm password", type="password")
                    submitted = st.form_submit_button("Create administrator", use_container_width=True)

            if submitted:
                if password != password_confirmation:
                    st.error("The passwords do not match.")
                else:
                    try:
                        response = requests.post(
                            f"{API_BASE_URL}/setup/admin",
                            json={
                                "username": username,
                                "full_name": full_name,
                                "password": password,
                            },
                            timeout=10,
                        )
                        response.raise_for_status()
                        st.success("Administrator created successfully. Please sign in.")
                        st.rerun()

                    except requests.HTTPError as exc:
                        try:
                            st.error(exc.response.json().get("detail", "Unable to create administrator."))
                        except ValueError:
                            st.error("Unable to create administrator.")

                    except requests.RequestException:
                        st.error("Unable to connect to the API. Ensure FastAPI is running.")
            return

        st.sidebar.caption("A role-based space for your team's trusted information.")
        st.sidebar.info("Sign in with an account created by your administrator.")
        intro_col, login_col = st.columns([1.15, 1], gap="large")
        with intro_col:
            st.subheader("Your team's knowledge, in one place.")
            st.write(
                "Ask questions in natural language and get answers grounded in approved department "
                "documents. Your role determines which knowledge collections are available."
            )
            st.markdown("**🔐 Role-based access**  \nOnly collections assigned to your account are available.")
            st.markdown("**📚 Answers grounded in your sources**  \nResponses use your department's knowledge base.")
        with login_col:
            st.subheader("Welcome back")
            st.caption("Sign in to continue to your workspace.")
            with st.form("login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Sign in", use_container_width=True)

        if submitted:
            try:
                response = requests.post(
                    f"{API_BASE_URL}/login",
                    json={"username": username, "password": password},
                    timeout=10,
                )

                if response.status_code == 401:
                    st.error("Invalid username or password.")
                else:
                    response.raise_for_status()
                    result = response.json()

                    st.session_state.token = result["access_token"]
                    st.session_state.user = {
                        "username": result["username"],
                        "full_name": result["full_name"],
                        "role": result["role"],
                        "is_admin": result["is_admin"],
                        "allowed_collections": result["allowed_collections"],
                    }
                    st.session_state.messages = []
                    st.rerun()

            except requests.RequestException:
                st.error("Unable to connect to the API. Ensure FastAPI is running.")

        return

    user = st.session_state.user
    st.sidebar.header("User Session")
    st.sidebar.write(f"Signed in as: **{user['full_name']}**")
    st.sidebar.write(f"Role: **{get_role_label(user['role'])}**")

    if st.sidebar.button("Logout"):
        st.session_state.user = None
        st.session_state.token = None
        st.session_state.messages = []
        st.rerun()

    if st.sidebar.button("Clear History"):
        st.session_state.messages = []
        st.rerun()

    if user["is_admin"]:
        st.subheader("User account management")
        st.write("Create accounts here and assign each account its department role.")
        with st.form("create_user_form", clear_on_submit=True):
            new_username = st.text_input("New username")
            new_full_name = st.text_input("Full name")
            role = st.selectbox(
                "Role",
                options=list(ASSIGNABLE_ROLES),
                format_func=lambda value: ASSIGNABLE_ROLES[value],
            )
            new_password = st.text_input("Temporary password (at least 12 characters)", type="password")
            new_password_confirmation = st.text_input("Confirm temporary password", type="password")
            submitted = st.form_submit_button("Create user")

        if submitted:
                if new_password != new_password_confirmation:
                    st.error("The passwords do not match.")
                else:
                    try:
                        response = requests.post(
                            f"{API_BASE_URL}/admin/users",
                            headers={
                                "Authorization": f"Bearer {st.session_state.token}"
                            },
                            json={
                                "username": new_username,
                                "full_name": new_full_name,
                                "password": new_password,
                                "role": role,
                            },
                            timeout=10,
                        )
                        response.raise_for_status()
                        st.success(f"Created account for {new_username.strip()}.")

                    except requests.HTTPError as exc:
                        try:
                            st.error(exc.response.json().get("detail", "Unable to create user."))
                        except ValueError:
                            st.error("Unable to create user.")

                    except requests.RequestException:
                        st.error("Unable to connect to the API. Ensure FastAPI is running.")
        return

    allowed_collections = get_available_collections(user)
    st.sidebar.header("Data Environment")
    collection_choice = st.sidebar.selectbox(
        "Select Department Database:",
        allowed_collections,
    )

    if not can_access_collection(user, collection_choice):
        st.error(f"Access denied: {user['full_name']} is not authorized for the {collection_choice} collection.")
        return

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if user_query := st.chat_input("Ask a question about this department..."):
        with st.chat_message("user"):
            st.markdown(user_query)
        st.session_state.messages.append({"role": "user", "content": user_query})

        safe_query = sanitize_pii(user_query)
        pii_detected = "[REDACTED" in safe_query
        if pii_detected:
            st.warning("🔒 Note: Sensitive personal variables were masked locally before processing.")

        # FastAPI is authoritative for collection authorization, PII sanitization,
        # and query-scope validation. The local checks below are only UI convenience.
        if not can_access_collection(user, collection_choice):
            bot_response = f"🛑 **Access Denied:** You do not have permission to query the **{collection_choice}** dataset."
            with st.chat_message("assistant"):
                st.markdown(bot_response)
            st.session_state.messages.append({"role": "assistant", "content": bot_response})
            return

        with st.spinner(f"Querying {collection_choice} knowledge sources..."):
            try:
                response = requests.post(
                    f"{API_BASE_URL}/chat",
                    headers={
                        "Authorization": f"Bearer {st.session_state.token}"
                    },
                    json={
                        "collection": collection_choice,
                        "question": safe_query,
                    },
                    timeout=120,
                )

                if response.status_code == 401:
                    st.session_state.user = None
                    st.session_state.token = None
                    st.session_state.messages = []
                    st.warning("Your session has expired. Please sign in again.")
                    st.rerun()

                if response.status_code in (400, 403):
                    detail = response.json().get("detail", "Your request was rejected.")
                    bot_response = f"🛑 **Request blocked:** {detail}"
                    with st.chat_message("assistant"):
                        st.markdown(bot_response)
                    st.session_state.messages.append({"role": "assistant", "content": bot_response})
                    return

                response.raise_for_status()
                bot_response = response.json()["answer"]
                with st.chat_message("assistant"):
                    st.markdown(bot_response)
                st.session_state.messages.append({"role": "assistant", "content": bot_response})

            except requests.RequestException:
                st.error("Unable to reach the API or retrieve an answer. Please try again.")
            except (ValueError, KeyError):
                st.error("The API returned an unexpected response.")


if __name__ == "__main__":
    if os.getenv("STREAMLIT_LAUNCHED") == "1" or st.runtime.exists():
        run_streamlit_ui()
    else:
        launch_streamlit_app()
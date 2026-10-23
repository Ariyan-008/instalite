import hashlib
import hmac
import secrets
import sqlite3
from pathlib import Path
from datetime import datetime

import streamlit as st

# ------------------------------------------------------------
# InstaLite: an Instagram-inspired local social media prototype
# ------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = APP_DIR / "uploads"
DB_PATH = APP_DIR / "instalite.db"
UPLOAD_DIR.mkdir(exist_ok=True)

st.set_page_config(
    page_title="InstaLite",
    page_icon="📸",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    html, body, [class*="css"] { font-family: Inter, sans-serif; }
    .block-container { max-width: 760px; padding-top: 1.5rem; }
    .brand {
        font-size: 2.2rem; font-weight: 800; letter-spacing: -1.5px;
        background: linear-gradient(90deg,#833ab4,#fd1d1d,#fcb045);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        margin-bottom: .1rem;
    }
    .subtle { color: #8b8b95; font-size: .9rem; }
    div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 16px; }
    button[kind="primary"] { border-radius: 10px; }
    </style>
    """,
    unsafe_allow_html=True,
)


def connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                bio TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                image_path TEXT NOT NULL,
                caption TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS likes (
                user_id INTEGER NOT NULL,
                post_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(user_id, post_id),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(post_id) REFERENCES posts(id)
            );
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                post_id INTEGER NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(post_id) REFERENCES posts(id)
            );
            CREATE TABLE IF NOT EXISTS follows (
                follower_id INTEGER NOT NULL,
                following_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(follower_id, following_id),
                CHECK(follower_id != following_id),
                FOREIGN KEY(follower_id) REFERENCES users(id),
                FOREIGN KEY(following_id) REFERENCES users(id)
            );
            """
        )


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 250_000)
    return salt.hex() + ":" + digest.hex()


def verify_password(password, stored):
    try:
        salt_hex, digest_hex = stored.split(":")
        candidate = hash_password(password, bytes.fromhex(salt_hex)).split(":")[1]
        return hmac.compare_digest(candidate, digest_hex)
    except (ValueError, TypeError):
        return False


def get_user_by_username(username):
    with connect() as con:
        return con.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()


def get_user_by_id(user_id):
    with connect() as con:
        return con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def count_for_user(user_id, table, column):
    # Table/column names here are fixed by the app, never user input.
    with connect() as con:
        return con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", (user_id,)
        ).fetchone()[0]


def get_post(post_id):
    with connect() as con:
        return con.execute(
            """
            SELECT p.*, u.username,
                (SELECT COUNT(*) FROM likes l WHERE l.post_id = p.id) AS like_count,
                EXISTS(SELECT 1 FROM likes l
                       WHERE l.post_id = p.id AND l.user_id = ?) AS liked_by_me
            FROM posts p JOIN users u ON u.id = p.user_id
            WHERE p.id = ?
            """,
            (st.session_state.user_id, post_id),
        ).fetchone()


def create_post(user_id, image_bytes, extension, caption):
    filename = f"{secrets.token_hex(12)}.{extension}"
    path = UPLOAD_DIR / filename
    path.write_bytes(image_bytes)
    with connect() as con:
        con.execute(
            "INSERT INTO posts(user_id, image_path, caption, created_at) VALUES(?,?,?,?)",
            (user_id, str(path), caption.strip(), now()),
        )


def toggle_like(user_id, post_id):
    with connect() as con:
        existing = con.execute(
            "SELECT 1 FROM likes WHERE user_id = ? AND post_id = ?",
            (user_id, post_id),
        ).fetchone()
        if existing:
            con.execute(
                "DELETE FROM likes WHERE user_id = ? AND post_id = ?",
                (user_id, post_id),
            )
        else:
            con.execute(
                "INSERT INTO likes(user_id, post_id, created_at) VALUES(?,?,?)",
                (user_id, post_id, now()),
            )


def toggle_follow(follower_id, following_id):
    if follower_id == following_id:
        return
    with connect() as con:
        exists = con.execute(
            "SELECT 1 FROM follows WHERE follower_id = ? AND following_id = ?",
            (follower_id, following_id),
        ).fetchone()
        if exists:
            con.execute(
                "DELETE FROM follows WHERE follower_id = ? AND following_id = ?",
                (follower_id, following_id),
            )
        else:
            con.execute(
                "INSERT INTO follows(follower_id, following_id, created_at) VALUES(?,?,?)",
                (follower_id, following_id, now()),
            )


def is_following(follower_id, following_id):
    with connect() as con:
        return con.execute(
            "SELECT 1 FROM follows WHERE follower_id = ? AND following_id = ?",
            (follower_id, following_id),
        ).fetchone() is not None


def add_comment(user_id, post_id, body):
    body = body.strip()
    if not body:
        return
    with connect() as con:
        con.execute(
            "INSERT INTO comments(user_id, post_id, body, created_at) VALUES(?,?,?,?)",
            (user_id, post_id, body[:1000], now()),
        )


def show_post(post):
    with st.container(border=True):
        left, right = st.columns([1, 5])
        with left:
            st.markdown("### 👤")
        with right:
            if st.button(
                f"@{post['username']}",
                key=f"profile_{post['id']}",
                type="tertiary",
            ):
                st.session_state.view_profile = post["username"]
                st.rerun()
            st.caption(post["created_at"])

        image_path = Path(post["image_path"])
        if image_path.exists():
            st.image(str(image_path), use_container_width=True)
        else:
            st.warning("This image file is missing.")

        if post["caption"]:
            st.markdown(f"**@{post['username']}**  {post['caption']}")

        like_col, comment_col = st.columns([1, 5])
        with like_col:
            label = "❤️ Liked" if post["liked_by_me"] else "🤍 Like"
            if st.button(label, key=f"like_{post['id']}"):
                toggle_like(st.session_state.user_id, post["id"])
                st.rerun()
        with comment_col:
            st.markdown(f"**{post['like_count']} likes**")

        with connect() as con:
            comments = con.execute(
                """
                SELECT c.body, c.created_at, u.username
                FROM comments c JOIN users u ON u.id = c.user_id
                WHERE c.post_id = ? ORDER BY c.id ASC
                """,
                (post["id"],),
            ).fetchall()

        for comment in comments[-5:]:
            st.markdown(f"**@{comment['username']}** {comment['body']}")
        if len(comments) > 5:
            st.caption(f"Showing the latest 5 of {len(comments)} comments.")

        with st.form(f"comment_form_{post['id']}", clear_on_submit=True):
            comment_text = st.text_input(
                "Add a comment",
                placeholder="Write a comment...",
                label_visibility="collapsed",
                max_chars=1000,
            )
            submitted = st.form_submit_button("Comment")
            if submitted:
                add_comment(st.session_state.user_id, post["id"], comment_text)
                st.rerun()


init_db()

if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "view_profile" not in st.session_state:
    st.session_state.view_profile = None

# ------------------------------- Login / registration
st.markdown('<div class="brand">InstaLite</div>', unsafe_allow_html=True)
st.caption("Share moments. Discover people. Built as a learning project.")

if st.session_state.user_id is None:
    login_tab, register_tab = st.tabs(["Log in", "Create account"])

    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Username").strip().lower()
            password = st.text_input("Password", type="password")
            submit_login = st.form_submit_button("Log in", type="primary", use_container_width=True)
        if submit_login:
            user = get_user_by_username(username)
            if user and verify_password(password, user["password_hash"]):
                st.session_state.user_id = user["id"]
                st.session_state.view_profile = None
                st.rerun()
            else:
                st.error("Incorrect username or password.")

    with register_tab:
        with st.form("register_form"):
            new_username = st.text_input("Choose a username").strip().lower()
            new_password = st.text_input("Choose a password", type="password")
            confirm_password = st.text_input("Confirm password", type="password")
            submit_register = st.form_submit_button(
                "Create account", type="primary", use_container_width=True
            )
        if submit_register:
            if len(new_username) < 3 or len(new_username) > 24:
                st.error("Username must be 3–24 characters.")
            elif not all(c.isalnum() or c in "._" for c in new_username):
                st.error("Use only letters, numbers, dots, and underscores in usernames.")
            elif len(new_password) < 8:
                st.error("Use a password with at least 8 characters.")
            elif new_password != confirm_password:
                st.error("Passwords do not match.")
            elif get_user_by_username(new_username):
                st.error("That username is already taken.")
            else:
                try:
                    with connect() as con:
                        con.execute(
                            "INSERT INTO users(username, password_hash, created_at) VALUES(?,?,?)",
                            (new_username, hash_password(new_password), now()),
                        )
                    st.success("Account created. Open the Log in tab to sign in.")
                except sqlite3.IntegrityError:
                    st.error("That username is already taken.")
    st.info("This prototype stores accounts, posts, likes, and comments locally on the computer running it.")
    st.stop()

# ------------------------------- Logged-in application
current_user = get_user_by_id(st.session_state.user_id)
if current_user is None:
    st.session_state.user_id = None
    st.rerun()

with st.sidebar:
    st.markdown(f"### 👋 @{current_user['username']}")
    st.caption("InstaLite menu")
    page = st.radio("Navigate", ["Feed", "Explore", "Create post", "My profile"])
    if st.button("Log out", use_container_width=True):
        st.session_state.user_id = None
        st.session_state.view_profile = None
        st.rerun()

# Keep navigation visible on small screens too.
nav1, nav2, nav3, nav4 = st.columns(4)
with nav1:
    if st.button("🏠 Feed", use_container_width=True):
        page = "Feed"
with nav2:
    if st.button("🔎 Explore", use_container_width=True):
        page = "Explore"
with nav3:
    if st.button("➕ Post", use_container_width=True):
        page = "Create post"
with nav4:
    if st.button("👤 Profile", use_container_width=True):
        page = "My profile"

if st.session_state.view_profile:
    page = "Profile"
    profile_username = st.session_state.view_profile
else:
    profile_username = current_user["username"]

if page == "Create post":
    st.subheader("Create a post")
    st.write("Share a photo with your followers and the community.")
    uploaded = st.file_uploader(
        "Choose an image",
        type=["png", "jpg", "jpeg", "webp"],
        help="Accepted formats: PNG, JPG, JPEG, WebP.",
    )
    caption = st.text_area("Caption", max_chars=2200, placeholder="Write a caption...")
    if uploaded:
        st.image(uploaded, caption="Preview", use_container_width=True)
    if st.button("Share post", type="primary", disabled=uploaded is None):
        ext = uploaded.name.rsplit(".", 1)[-1].lower()
        if ext == "jpeg":
            ext = "jpg"
        create_post(current_user["id"], uploaded.getvalue(), ext, caption)
        st.success("Your post has been shared.")
        st.rerun()

elif page == "My profile" or page == "Profile":
    profile = get_user_by_username(profile_username)
    if not profile:
        st.error("User not found.")
        st.session_state.view_profile = None
    else:
        if profile["id"] != current_user["id"]:
            st.session_state.view_profile = profile["username"]
        else:
            st.session_state.view_profile = None

        posts_count = count_for_user(profile["id"], "posts", "user_id")
        followers = count_for_user(profile["id"], "follows", "following_id")
        following = count_for_user(profile["id"], "follows", "follower_id")
        st.markdown(f"## 👤 @{profile['username']}")
        st.caption(profile["bio"] or "No bio yet.")
        a, b, c = st.columns(3)
        a.metric("Posts", posts_count)
        b.metric("Followers", followers)
        c.metric("Following", following)

        if profile["id"] != current_user["id"]:
            label = "Following" if is_following(current_user["id"], profile["id"]) else "Follow"
            if st.button(label, type="primary"):
                toggle_follow(current_user["id"], profile["id"])
                st.rerun()
            if st.button("Back to feed"):
                st.session_state.view_profile = None
                st.rerun()
        else:
            with st.expander("Edit bio"):
                with st.form("bio_form"):
                    bio_text = st.text_area("Bio", value=profile["bio"], max_chars=160)
                    if st.form_submit_button("Save bio"):
                        with connect() as con:
                            con.execute("UPDATE users SET bio = ? WHERE id = ?", (bio_text.strip(), profile["id"]))
                        st.success("Bio updated.")
                        st.rerun()

        st.divider()
        st.subheader("Posts")
        with connect() as con:
            user_posts = con.execute(
                "SELECT id FROM posts WHERE user_id = ? ORDER BY id DESC",
                (profile["id"],),
            ).fetchall()
        if not user_posts:
            st.info("No posts yet. Share your first photo from the Post tab.")
        for row in user_posts:
            post = get_post(row["id"])
            if post:
                show_post(post)

elif page == "Explore":
    st.subheader("Explore")
    st.caption("Discover posts from the community.")
    with connect() as con:
        post_rows = con.execute(
            "SELECT id FROM posts ORDER BY id DESC LIMIT 50"
        ).fetchall()
    if not post_rows:
        st.info("No posts yet. Create an account with another browser/session or share the first post.")
    for row in post_rows:
        post = get_post(row["id"])
        if post:
            show_post(post)

else:  # Feed
    st.subheader("Your feed")
    st.caption("Recent photos from everyone on this demo.")
    with connect() as con:
        post_rows = con.execute(
            "SELECT id FROM posts ORDER BY id DESC LIMIT 50"
        ).fetchall()
    if not post_rows:
        st.markdown("### Your feed is waiting for its first photo.")
        st.write("Create a post, add a caption, and it will appear here.")
        if st.button("Create your first post", type="primary"):
            page = "Create post"
            st.rerun()
    for row in post_rows:
        post = get_post(row["id"])
        if post:
            show_post(post)

st.divider()
st.caption("InstaLite demo • Not affiliated with Instagram or Meta.")

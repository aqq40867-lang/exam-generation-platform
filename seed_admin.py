"""
One-off command line script to create the very first admin account.

Why this needs to exist as a script (and not a web page): before any admin
account exists, there's no one who could log in to an "admin only" page to
create one. So the very first admin has to be inserted directly, from the
command line, by whoever is setting up the deployment.

Usage:
    python seed_admin.py <username> <password>

Example:
    python seed_admin.py alice "s0me-strong-pw"

After this runs once, log in as that user at /login and use the
"User Management" page (/admin/users) to create/manage everyone else -
you should not need to run this script again unless you lock yourself out.
"""

import sys
import getpass

from database import create_user, get_user_by_username


def main():
    if len(sys.argv) == 2:
        username = sys.argv[1]
        password = getpass.getpass("Password for new admin: ")
    elif len(sys.argv) == 3:
        username = sys.argv[1]
        password = sys.argv[2]
    else:
        print("Usage: python seed_admin.py <username> [password]")
        print("(if password is omitted, you'll be prompted for it securely)")
        sys.exit(1)

    if get_user_by_username(username):
        print(f"Error: a user named '{username}' already exists.")
        sys.exit(1)

    if not password:
        print("Error: password cannot be empty.")
        sys.exit(1)

    new_id = create_user(username, password, role="admin")

    if new_id is None:
        print(f"Error: could not create user '{username}' (already taken?).")
        sys.exit(1)

    print(f"Admin account '{username}' created (id={new_id}).")
    print("Log in at /login, then go to /admin/users to manage other accounts.")


if __name__ == "__main__":
    main()

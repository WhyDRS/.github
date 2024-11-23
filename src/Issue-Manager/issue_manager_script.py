import os
import re
import time
import sys
from datetime import datetime, timedelta
from github import GithubIntegration, Github
from github.GithubException import GithubException, RateLimitExceededException

# --------------------------------- Overview ----------------------------------
# This script automates the process of adding new issues from any repository
# within the 'WhyDRS' organization to a specified GitHub Project. It handles
# various edge cases to ensure robustness.

# --------------------------- Configuration Variables -------------------------

app_id = os.environ['APP_ID']
private_key = os.environ['APP_PRIVATE_KEY']

org_name = 'WhyDRS'
project_number = 3

lock_file = '/tmp/why_drs_issue_manager.lock'

# -------------------------- GitHub Authentication ----------------------------

integration = GithubIntegration(app_id, private_key)

# Fetch all installations of your GitHub App
installations = integration.get_installations()

if not installations:
    print("No installations found for the GitHub App.")
    sys.exit(1)

# Since your app likely has one installation, use it directly
installation = installations[0]
installation_id = installation.id

# Generate an access token for the installation
try:
    access_token = integration.get_access_token(installation_id).token
except GithubException as e:
    print(f"Failed to get access token: {e.data}")
    sys.exit(1)

# Initialize a GitHub client using the access token
g = Github(login_or_token=access_token)

# ----------------------- Fetch Organization and Project ----------------------

# Fetch the organization object
try:
    org = g.get_organization(org_name)
except GithubException as e:
    print(f"Failed to get organization {org_name}: {e.data}")
    sys.exit(1)

# Fetch all projects in the organization
try:
    projects = org.get_projects()
except GithubException as e:
    print(f"Failed to get projects for organization {org_name}: {e.data}")
    sys.exit(1)

project = None

# Search for the project with the specified project number
for p in projects:
    if p.number == project_number:
        project = p
        break

if not project:
    print(f"Project number {project_number} not found.")
    sys.exit(1)

# ----------------------- Prevent Overlapping Runs ----------------------------

if os.path.exists(lock_file):
    if time.time() - os.path.getmtime(lock_file) > 3600:
        os.remove(lock_file)
    else:
        print("Another instance of the script is already running. Exiting to prevent overlap.")
        sys.exit(1)
else:
    open(lock_file, 'w').close()

# -------------------------- Main Processing Loop -----------------------------

try:
    since_time = datetime.utcnow() - timedelta(days=1, minutes=5)

    # Fetch all repositories within the organization
    repos = org.get_repos()

    # Iterate over each repository
    for repo in repos:
        if repo.archived or repo.fork or not repo.has_issues:
            continue

        column_name = re.sub(r'[^a-zA-Z0-9_\- ]', '_', repo.name)

        # Fetch open issues created since 'since_time'
        issues = repo.get_issues(state='open', since=since_time)

        for issue in issues:
            if issue.pull_request is not None:
                continue

            if issue.created_at < since_time:
                continue

            labels = [label.name for label in issue.labels]
            if 'DoNotAddToProject' in labels:
                continue

            # Check if the issue is already included in the project
            in_project = False
            columns = project.get_columns()
            for column in columns:
                cards = column.get_cards()
                for card in cards:
                    try:
                        content = card.get_content()
                        if content and content.id == issue.id:
                            in_project = True
                            break
                    except:
                        continue
                if in_project:
                    break

            if not in_project:
                # Find or create the column
                column = next((col for col in columns if col.name == column_name), None)
                if not column:
                    column = project.create_column(column_name)

                # Add the issue to the project column
                column.create_card(content_id=issue.id, content_type="Issue")
                print(f"Issue #{issue.number} in {repo.name} added to project.")

except RateLimitExceededException as e:
    reset_time = datetime.fromtimestamp(g.rate_limiting_resettime)
    print(f"Rate limit exceeded. Resets at {reset_time}.")
except Exception as e:
    print(f"An unexpected error occurred: {e}")
finally:
    if os.path.exists(lock_file):
        os.remove(lock_file)

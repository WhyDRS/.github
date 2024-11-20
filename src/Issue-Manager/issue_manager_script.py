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
# various edge cases to ensure robustness, such as rate limiting, time zone
# discrepancies, duplicate issues, and more.

# The script performs the following main tasks:
# 1. Authenticates with GitHub using a GitHub App.
# 2. Fetches the specified organization and project.
# 3. Iterates over all repositories in the organization.
# 4. For each repository, it processes new issues created within the last day.
# 5. Adds new issues to the project under columns named after the repository.
# 6. Handles edge cases like archived repositories, forked repositories,
#    rate limiting, and more.

# --------------------------- Configuration Variables -------------------------

# Environment variables for GitHub App credentials
app_id = os.environ['APP_ID']                # GitHub App ID
private_key = os.environ['APP_PRIVATE_KEY']  # GitHub App private key in PEM format

# Organization and project details
org_name = 'WhyDRS'       # Your organization's name
project_number = 3        # The number of your project (from the project's URL)

# Lock file path for preventing overlapping runs
lock_file = '/tmp/why_drs_issue_manager.lock'

# -------------------------- GitHub Authentication ----------------------------

# Initialize a GitHubIntegration instance with your App ID and private key
integration = GithubIntegration(app_id, private_key)

# Fetch all installations of your GitHub App
installations = integration.get_installations()

if not installations:
    # No installations detected for the GitHub App
    print("No installations found for the GitHub App.")
    sys.exit(1)  # Exit the script with an error code

# Edge Case 25: Changes in Repository Ownership
# Handle multiple installations by selecting the correct one based on the organization name
installation_id = None
for installation in installations:
    try:
        account = installation.account  # Corrected line
        if account.login.lower() == org_name.lower():
            installation_id = installation.id  # Get the ID of the installation for your organization
            break
    except GithubException as e:
        print(f"Failed to get account for installation {installation.id}: {e.data}")
        continue

if not installation_id:
    print(f"No installation found for organization {org_name}.")
    sys.exit(1)

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

project = None  # Initialize the project variable

# Search for the project with the specified project number
for p in projects:
    if p.number == project_number:
        project = p  # Assign the found project
        break        # Exit the loop once the project is found

if not project:
    print(f"Project number {project_number} not found.")
    sys.exit(1)

# ----------------------- Prevent Overlapping Runs ----------------------------

# Edge Case 16: Concurrency and Race Conditions
# Implement a lock file mechanism to prevent overlapping runs
if os.path.exists(lock_file):
    # Check if the lock file is older than 1 hour
    if time.time() - os.path.getmtime(lock_file) > 3600:
        os.remove(lock_file)  # Remove stale lock file
    else:
        print("Another instance of the script is already running. Exiting to prevent overlap.")
        sys.exit(1)
else:
    open(lock_file, 'w').close()  # Create the lock file

# -------------------------- Main Processing Loop -----------------------------

try:
    # Edge Case 2 and 12: Time Zone and Timestamp Issues
    # Calculate the timestamp for 24 hours ago with a 5-minute buffer
    since_time = datetime.utcnow() - timedelta(days=1, minutes=5)  # 5-minute buffer

    # Fetch all repositories within the organization
    try:
        repos = org.get_repos()
    except GithubException as e:
        print(f"Failed to get repositories for organization {org_name}: {e.data}")
        sys.exit(1)

    # Iterate over each repository
    for repo in repos:
        # Edge Case 25: Changes in Repository Ownership
        # Ensure the repository belongs to the organization
        if repo.organization.login.lower() != org_name.lower():
            continue  # Skip repositories not belonging to the organization

        # Edge Case 5: Repositories with Issues Disabled
        if not repo.has_issues:
            continue  # Skip repositories without issues enabled

        # Edge Case 6: Archived or Disabled Repositories
        if repo.archived:
            continue  # Skip archived repositories

        # Edge Case 21: Repository Forks
        if repo.fork:
            continue  # Skip forked repositories

        # Edge Case 8 and 9: Renamed or Special Character Repositories
        # Sanitize repository name for column name
        column_name = re.sub(r'[^a-zA-Z0-9_\- ]', '_', repo.name)

        # Edge Case 24: Exception Handling in Loops
        try:
            # Fetch open issues created since 'since_time'
            issues = repo.get_issues(state='open', since=since_time)
        except GithubException as e:
            print(f"Failed to get issues for repository {repo.name}: {e.data}")
            continue  # Proceed to the next repository

        # Iterate over each issue
        for issue in issues:
            # Edge Case 14: Handling Pull Requests
            if issue.pull_request is not None:
                continue  # Skip pull requests

            # Edge Case 12: Issues Created Before the Last Run
            if issue.created_at < since_time:
                continue  # Skip issues created before 'since_time'

            # Edge Case 29: Handling Issues Without a Repository
            if not issue.repository:
                continue  # Skip issues without a repository

            # Edge Case 17: Manual Modifications to the Project
            # Check for a label indicating the issue should not be added
            labels = [label.name for label in issue.labels]
            if 'DoNotAddToProject' in labels:
                continue  # Respect manual choice to exclude the issue

            # Edge Case 3: Duplicate Issues in the Project
            # Check if the issue is already included in the project
            in_project = False  # Flag to indicate presence in the project

            # Edge Case 22: Reaching Maximum API Page Limits
            # Fetch project columns with proper pagination
            try:
                columns = project.get_columns()
            except GithubException as e:
                print(f"Failed to get columns for project {project.title}: {e.data}")
                continue  # Proceed to the next issue

            for column in columns:
                try:
                    cards = column.get_cards()
                except GithubException as e:
                    print(f"Failed to get cards for column {column.name}: {e.data}")
                    continue  # Proceed to the next column

                for card in cards:
                    try:
                        # Compare card content ID with issue ID to check for duplicates
                        if card.get_content().id == issue.id:
                            in_project = True  # Issue is already in the project
                            break  # Exit inner loop
                    except GithubException as e:
                        print(f"Failed to get content for card: {e.data}")
                        continue  # Proceed to the next card
                    except AttributeError:
                        # Card does not have content (maybe it's a note), skip it
                        continue

                if in_project:
                    break  # Exit outer loop if issue is found

            # If the issue is not in the project, proceed to add it
            if not in_project:

                # Attempt to find a column named after the repository
                column = None  # Initialize the column variable
                for col in columns:
                    if col.name == column_name:  # Check if column name matches sanitized repository name
                        column = col  # Assign the existing column
                        break  # Exit the loop

                # If the column does not exist, create it
                if not column:
                    try:
                        column = project.create_column(column_name)  # Create a new column
                    except GithubException as e:
                        print(f"Failed to create column {column_name}: {e.data}")
                        continue  # Proceed to the next issue

                # Add the issue to the project column
                try:
                    column.create_card(content_id=issue.id, content_type="Issue")  # Add the issue as a card
                    print(f"Issue #{issue.number} in {repo.name} added to project.")
                except GithubException as e:
                    print(f"Failed to add issue #{issue.number} to column {column_name}: {e.data}")
                    continue  # Proceed to the next issue

            # Edge Case 11: Handling Closed or Reopened Issues
            # This script does not remove closed issues to avoid unintended deletions

except RateLimitExceededException as e:
    # Edge Case 1: Rate Limiting
    # Handle the rate limit exception by informing the user
    reset_time = datetime.fromtimestamp(g.rate_limiting_resettime)
    print(f"Rate limit exceeded. Resets at {reset_time}.")
except Exception as e:
    # Edge Case 18: Error Handling and Notifications
    # Catch any other exceptions and print the error message
    print(f"An unexpected error occurred: {e}")
finally:
    # Edge Case 16: Remove the lock file to ensure it's removed even if errors occur
    if os.path.exists(lock_file):
        os.remove(lock_file)  # Remove the lock file

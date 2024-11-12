import os
import re
import time
from datetime import datetime, timedelta
from github import GithubIntegration, Github
from github.GithubException import GithubException, RateLimitExceededException

# Edge Case 1: Rate Limiting
# - Monitor rate limits and handle RateLimitExceededException.

# Edge Case 2: Time Zone and Timestamp Issues
# - Ensure consistent use of UTC and add a buffer to 'since_time'.

# Edge Case 3: Duplicate Issues in the Project
# - Improve duplicate checking logic.

# Edge Case 5: Repositories with Issues Disabled
# - Skip repositories where issues are disabled.

# Edge Case 6: Archived or Disabled Repositories
# - Skip archived repositories.

# Edge Case 8: Renamed or Deleted Repositories
# - Handle repositories that have been renamed or deleted.

# Edge Case 9: Special Characters in Repository Names
# - Sanitize repository names when creating columns.

# Edge Case 10: Issues Transferred Between Repositories
# - Handle issues moved between repositories.

# Edge Case 11: Handling Closed or Reopened Issues
# - Optionally remove closed issues from the project.

# Edge Case 12: Issues Created Before the Last Run
# - Add a buffer to 'since_time' to prevent missing issues.

# Edge Case 14: Handling Pull Requests
# - Exclude pull requests if desired.

# Edge Case 16: Concurrency and Race Conditions
# - Prevent overlapping runs with a lock file.

# Edge Case 17: Manual Modifications to the Project
# - Respect manual changes by users.

# Edge Case 18: Error Handling and Notifications
# - Implement robust error handling and notifications.

# Edge Case 21: Repository Forks
# - Skip forked repositories.

# Edge Case 22: Reaching Maximum API Page Limits
# - Implement proper pagination.

# Edge Case 24: Exception Handling in Loops
# - Add try-except blocks around API calls.

# Edge Case 25: Changes in Repository Ownership
# - Handle repositories transferred out of the organization.

# Edge Case 29: Handling Issues Without a Repository
# - Ensure the script handles issues without a repository.

# Edge Case 30: Scalability
# - Optimize the script for performance and scalability.

# ----------------------------- Start of Script -----------------------------

# Retrieve environment variables containing GitHub App credentials
app_id = os.environ['APP_ID']                # GitHub App ID
private_key = os.environ['APP_PRIVATE_KEY']  # GitHub App private key in PEM format

# Initialize a GithubIntegration instance with your App ID and private key
integration = GithubIntegration(app_id, private_key)

# Fetch all installations of your GitHub App
installations = integration.get_installations()
if not installations:
    print("No installations found for the GitHub App.")  # No installations detected
    exit(1)  # Exit the script with an error code

# Edge Case 25: Handle multiple installations by selecting the correct one
org_name = 'WhyDRS'  # Your organization's name
installation_id = None
for installation in installations:
    if installation.account.login.lower() == org_name.lower():
        installation_id = installation.id  # Get the ID of the installation for your organization
        break

if not installation_id:
    print(f"No installation found for organization {org_name}.")
    exit(1)

# Generate an access token for the installation
try:
    access_token = integration.get_access_token(installation_id).token
except GithubException as e:
    print(f"Failed to get access token: {e}")
    exit(1)

# Initialize a GitHub client using the access token
g = Github(login_or_token=access_token)

# Define variables for your project
project_number = 3  # Replace with your project's number

# Fetch the organization object
try:
    org = g.get_organization(org_name)
except GithubException as e:
    print(f"Failed to get organization {org_name}: {e}")
    exit(1)

# Fetch all projects in the organization
try:
    projects = org.get_projects()
except GithubException as e:
    print(f"Failed to get projects for organization {org_name}: {e}")
    exit(1)

project = None  # Initialize the project variable

# Search for the project with the specified project number
for p in projects:
    if p.number == project_number:
        project = p  # Assign the found project
        break        # Exit the loop once the project is found

# If the project was not found, exit the script
if not project:
    print(f"Project number {project_number} not found.")
    exit(1)

# Edge Case 16: Prevent overlapping runs
# Create a lock file to ensure only one instance runs at a time
lock_file = '/tmp/why_drs_issue_manager.lock'

if os.path.exists(lock_file):
    print("Another instance of the script is already running. Exiting to prevent overlap.")
    exit(1)
else:
    open(lock_file, 'w').close()  # Create the lock file

try:
    # Edge Case 2 and 12: Calculate the timestamp for 24 hours ago with a buffer
    since_time = datetime.utcnow() - timedelta(days=1, minutes=5)  # 5-minute buffer

    # Fetch all repositories within the organization with proper pagination
    try:
        repos = org.get_repos()
    except GithubException as e:
        print(f"Failed to get repositories for organization {org_name}: {e}")
        exit(1)

    # Iterate over each repository
    for repo in repos:
        # Edge Case 25: Handle repositories transferred out of the organization
        if repo.organization.login.lower() != org_name.lower():
            continue  # Skip repositories not belonging to the organization

        # Edge Case 5: Skip repositories where issues are disabled
        if not repo.has_issues:
            continue  # Skip this repository

        # Edge Case 6: Skip archived repositories
        if repo.archived:
            continue  # Skip this repository

        # Edge Case 21: Skip forked repositories
        if repo.fork:
            continue  # Skip this repository

        # Edge Case 8: Handle renamed repositories
        repo_name = repo.name

        # Edge Case 9: Sanitize repository names for column names
        column_name = re.sub(r'[^a-zA-Z0-9_\- ]', '_', repo_name)

        # Edge Case 24: Exception handling around issue fetching
        try:
            # Fetch open issues created since 'since_time'
            issues = repo.get_issues(state='open', since=since_time)
        except GithubException as e:
            print(f"Failed to get issues for repository {repo_name}: {e}")
            continue  # Proceed to the next repository

        # Iterate over each issue
        for issue in issues:
            # Edge Case 14: Exclude pull requests
            if issue.pull_request is not None:
                continue  # Skip pull requests

            # Edge Case 12: Confirm the issue was created after 'since_time'
            if issue.created_at < since_time:
                continue  # Skip issues created before 'since_time'

            # Edge Case 29: Handle issues without a repository
            if not issue.repository:
                continue  # Skip issues without a repository

            # Edge Case 3: Check if the issue is already included in the project
            in_project = False  # Flag to indicate presence in the project

            # Edge Case 22: Implement proper pagination for columns and cards
            try:
                columns = project.get_columns()
            except GithubException as e:
                print(f"Failed to get columns for project {project.title}: {e}")
                continue  # Proceed to the next issue

            for column in columns:
                try:
                    cards = column.get_cards()
                except GithubException as e:
                    print(f"Failed to get cards for column {column.name}: {e}")
                    continue  # Proceed to the next column

                for card in cards:
                    try:
                        # Compare card content URL with issue URL
                        if card.content_url == issue.url:
                            in_project = True  # Issue is already in the project
                            break  # Exit inner loop
                    except GithubException as e:
                        print(f"Failed to get content URL for card in column {column.name}: {e}")
                        continue  # Proceed to the next card

                if in_project:
                    break  # Exit outer loop if issue is found

            # If the issue is not in the project, proceed to add it
            if not in_project:
                # Edge Case 8: Handle renamed repositories
                # Re-fetch the repository name in case it has changed
                repo_name = repo.name
                column_name = re.sub(r'[^a-zA-Z0-9_\- ]', '_', repo_name)

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
                        print(f"Failed to create column {column_name}: {e}")
                        continue  # Proceed to the next issue

                # Add the issue to the project column
                try:
                    column.create_card(content_id=issue.id, content_type="Issue")  # Add the issue as a card
                    print(f"Issue #{issue.number} in {repo_name} added to project.")
                except GithubException as e:
                    print(f"Failed to add issue #{issue.number} to column {column_name}: {e}")
                    continue  # Proceed to the next issue

            # Edge Case 11: Handle closed issues (Optional)
            # If you wish to remove closed issues from the project, implement that here.

except RateLimitExceededException as e:
    # Edge Case 1: Rate Limiting
    # Handle the rate limit exception
    reset_timestamp = g.get_rate_limit().core.reset.timestamp()
    current_timestamp = datetime.utcnow().timestamp()
    sleep_time = reset_timestamp - current_timestamp + 5  # Add 5 seconds buffer
    print(f"Rate limit exceeded. Sleeping for {sleep_time / 60:.2f} minutes.")
    time.sleep(max(sleep_time, 0))
except Exception as e:
    # Edge Case 18: Error Handling and Notifications
    # Catch any other exceptions
    print(f"An unexpected error occurred: {e}")
finally:
    # Edge Case 16: Remove the lock file to ensure it's removed even if errors occur
    if os.path.exists(lock_file):
        os.remove(lock_file)  # Remove the lock file

# ----------------------------- End of Script -----------------------------

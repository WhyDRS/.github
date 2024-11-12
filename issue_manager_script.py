import os
from datetime import datetime, timedelta
from github import GithubIntegration, Github

# Get environment variables
app_id = os.environ['APP_ID']
private_key = os.environ['APP_PRIVATE_KEY']

# Initialize GitHub Integration
integration = GithubIntegration(app_id, private_key)

# Get installation ID
installations = integration.get_installations()
if not installations:
    print("No installations found for the GitHub App.")
    exit(1)

installation_id = installations[0].id

# Get an access token
access_token = integration.get_access_token(installation_id).token

# Initialize GitHub client
g = Github(login_or_token=access_token)

# Variables
org_name = 'WhyDRS'  # Your organization name
project_number = 1   # Replace with your project's number

# Get the organization
org = g.get_organization(org_name)

# Get the project
projects = org.get_projects()
project = None
for p in projects:
    if p.number == project_number:
        project = p
        break

if not project:
    print(f"Project number {project_number} not found.")
    exit(1)

# Calculate time since last run (24 hours ago)
since_time = datetime.utcnow() - timedelta(days=1)

# Get all repositories in the organization
repos = org.get_repos()

for repo in repos:
    # Get issues created since the last run
    issues = repo.get_issues(state='open', since=since_time)

    for issue in issues:
        # Check if the issue was created since the last run
        if issue.created_at < since_time:
            continue

        # Check if issue is already in the project
        in_project = False
        for column in project.get_columns():
            for card in column.get_cards():
                if card.content_url == issue.url:
                    in_project = True
                    break
            if in_project:
                break

        if not in_project:
            # Get or create column named after the repository
            columns = project.get_columns()
            column = None
            for col in columns:
                if col.name == repo.name:
                    column = col
                    break

            if not column:
                # Create a new column
                column = project.create_column(repo.name)

            # Add the issue to the project column
            column.create_card(content_id=issue.id, content_type="Issue")
            print(f"Issue #{issue.number} in {repo.name} added to project.")

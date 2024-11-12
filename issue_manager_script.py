import os
from datetime import datetime, timedelta
from github import GithubIntegration, Github

# Retrieve environment variables containing GitHub App credentials
app_id = os.environ['APP_ID']                # GitHub App ID
private_key = os.environ['APP_PRIVATE_KEY']  # GitHub App private key in PEM format

# Initialize a GitHubIntegration instance with your App ID and private key
integration = GithubIntegration(app_id, private_key)

# Fetch all installations of your GitHub App
installations = integration.get_installations()
if not installations:
    print("No installations found for the GitHub App.")  # No installations detected
    exit(1)  # Exit the script with an error code

# Obtain the installation ID (assuming the app is installed once)
installation_id = installations[0].id  # Get the ID of the first installation

# Generate an access token for the installation
access_token = integration.get_access_token(installation_id).token

# Initialize a GitHub client using the access token
g = Github(login_or_token=access_token)

# Define variables for your organization and project
org_name = 'WhyDRS'       # Your organization's name
project_number = 3        # The number of your project (from the project's URL)

# Retrieve the organization object
org = g.get_organization(org_name)

# Fetch all projects in the organization
projects = org.get_projects()
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

# Calculate the timestamp for 24 hours ago
since_time = datetime.utcnow() - timedelta(days=1)

# Fetch all repositories within the organization
repos = org.get_repos()

# Iterate over each repository
for repo in repos:
    # Fetch open issues created since 'since_time'
    issues = repo.get_issues(state='open', since=since_time)

    # Iterate over each issue
    for issue in issues:
        # Confirm the issue was created after 'since_time'
        if issue.created_at < since_time:
            continue  # Skip issues created before 'since_time'

        # Check if the issue is already included in the project
        in_project = False  # Flag to indicate presence in the project
        for column in project.get_columns():       # Iterate over project columns
            for card in column.get_cards():        # Iterate over cards in the column
                if card.content_url == issue.url:  # Compare card content URL with issue URL
                    in_project = True              # Issue is already in the project
                    break                          # Exit inner loop
            if in_project:
                break  # Exit outer loop if issue is found

        # If the issue is not in the project, proceed to add it
        if not in_project:
            # Attempt to find a column named after the repository
            columns = project.get_columns()
            column = None  # Initialize the column variable
            for col in columns:
                if col.name == repo.name:  # Check if column name matches repository name
                    column = col           # Assign the existing column
                    break                  # Exit the loop

            # If the column does not exist, create it
            if not column:
                column = project.create_column(repo.name)  # Create a new column

            # Add the issue to the project column
            column.create_card(content_id=issue.id, content_type="Issue")  # Add the issue as a card
            print(f"Issue #{issue.number} in {repo.name} added to project.")  # Confirmation message

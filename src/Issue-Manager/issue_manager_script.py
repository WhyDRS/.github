import os
import re
import time
import sys
import requests
from datetime import datetime, timedelta, timezone
from github import GithubIntegration, Github, Auth
from github.GithubException import GithubException, RateLimitExceededException

# --------------------------------- Overview ----------------------------------
# [Overview comments remain unchanged]

# --------------------------- Configuration Variables -------------------------

app_id = os.environ['APP_ID']
private_key = os.environ['APP_PRIVATE_KEY']

org_name = 'WhyDRS'
project_number = 3  # The number of your project (from the project's URL)

lock_file = '/tmp/why_drs_issue_manager.lock'

# -------------------------- GitHub Authentication ----------------------------

# Initialize an Auth.AppAuth instance
auth = Auth.AppAuth(
    app_id=int(app_id),
    private_key=private_key,
)

jwt_token = auth.token  # This generates the JWT

# Initialize GithubIntegration
integration = GithubIntegration(app_id, private_key)

# Headers for API requests
jwt_headers = {
    "Authorization": f"Bearer {jwt_token}",
    "Accept": "application/vnd.github.v3+json"
}

# Get the installation ID for the organization using the REST API
installation_url = f"https://api.github.com/orgs/{org_name}/installation"
response = requests.get(installation_url, headers=jwt_headers)

if response.status_code == 200:
    installation_id = response.json()['id']
    print(f"Installation ID for {org_name} is {installation_id}")
else:
    print(f"Failed to get installation ID for organization {org_name}: {response.text}")
    sys.exit(1)

# Generate an access token for the installation
try:
    access_token = integration.get_access_token(installation_id).token
except GithubException as e:
    print(f"Failed to get access token: {e.data}")
    sys.exit(1)

# Headers for GraphQL API requests using the access token
headers = {
    "Authorization": f"Bearer {access_token}",
    "Accept": "application/vnd.github.starfox-preview+json"  # Required for Projects (Beta) API
}

# ----------------------- Fetch Organization and Project ----------------------

# Fetch the organization's node ID using the REST API
org_url = f"https://api.github.com/orgs/{org_name}"
response = requests.get(org_url, headers=headers)
if response.status_code != 200:
    print(f"Failed to get organization {org_name}: {response.text}")
    sys.exit(1)

org_data = response.json()
organization_node_id = org_data["node_id"]

# Fetch the project using the GraphQL API
graphql_url = "https://api.github.com/graphql"

# GraphQL query to get the project ID
project_query = """
query($org: String!, $projectNumber: Int!) {
  organization(login: $org) {
    projectV2(number: $projectNumber) {
      id
      title
    }
  }
}
"""

variables = {
    "org": org_name,
    "projectNumber": project_number
}

response = requests.post(
    graphql_url,
    json={"query": project_query, "variables": variables},
    headers=headers
)

if response.status_code != 200 or 'errors' in response.json():
    print(f"GraphQL query failed: {response.text}")
    sys.exit(1)

response_data = response.json()
project_data = response_data.get("data", {}).get("organization", {}).get("projectV2")

if not project_data:
    print(f"Project number {project_number} not found.")
    sys.exit(1)

project_id = project_data["id"]
project_title = project_data["title"]
print(f"Found project: {project_title}")

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
    since_time = datetime.now(timezone.utc) - timedelta(days=1, minutes=5)
    since_time_iso = since_time.isoformat()

    # Fetch all repositories within the organization
    g = Github(access_token)
    org = g.get_organization(org_name)
    repos = org.get_repos()

    for repo in repos:
        print(f"Processing repository: {repo.full_name}")
        if repo.archived or repo.fork or not repo.has_issues:
            print(f"Skipping repository {repo.full_name}: archived, forked, or issues disabled.")
            continue

        # Fetch all open issues
        issues = repo.get_issues(state='open')

        for issue in issues:
            print(f"Checking issue #{issue.number} in {repo.full_name}")

            if issue.pull_request is not None:
                print(f"Issue #{issue.number} is a pull request. Skipping.")
                continue

            if issue.created_at < since_time:
                print(f"Issue #{issue.number} was created before since_time. Skipping.")
                continue

            labels = [label.name for label in issue.labels]
            if 'DoNotAddToProject' in labels:
                print(f"Issue #{issue.number} has 'DoNotAddToProject' label. Skipping.")
                continue

            # Get the issue's GraphQL ID
            issue_id_query = """
            query($owner: String!, $repo: String!, $number: Int!) {
              repository(owner: $owner, name: $repo) {
                issue(number: $number) {
                  id
                }
              }
            }
            """

            variables = {
                "owner": repo.owner.login,
                "repo": repo.name,
                "number": issue.number
            }

            response = requests.post(
                graphql_url,
                json={"query": issue_id_query, "variables": variables},
                headers=headers
            )

            if response.status_code != 200 or 'errors' in response.json():
                print(f"GraphQL query failed: {response.text}")
                continue

            issue_data = response.json().get("data", {}).get("repository", {}).get("issue")
            if not issue_data:
                print(f"Failed to get GraphQL ID for issue #{issue.number}")
                continue

            issue_graphql_id = issue_data["id"]

            # Check if the issue is already in the project
            check_item_query = """
            query($issueId: ID!) {
              node(id: $issueId) {
                ... on Issue {
                  projectItems(first: 100) {
                    nodes {
                      project {
                        id
                      }
                    }
                  }
                }
              }
            }
            """

            variables = {
                "issueId": issue_graphql_id
            }

            response = requests.post(
                graphql_url,
                json={"query": check_item_query, "variables": variables},
                headers=headers
            )

            if response.status_code != 200 or 'errors' in response.json():
                print(f"GraphQL query failed: {response.text}")
                continue

            project_items = response.json().get("data", {}).get("node", {}).get("projectItems", {}).get("nodes", [])

            already_in_project = False
            for item in project_items:
                if item.get("project", {}).get("id") == project_id:
                    already_in_project = True
                    break

            if already_in_project:
                print(f"Issue #{issue.number} is already in the project. Skipping.")
                continue

            # Add the issue to the project
            add_item_mutation = """
            mutation($input: AddProjectV2ItemByIdInput!) {
              addProjectV2ItemById(input: $input) {
                item {
                  id
                }
              }
            }
            """

            variables = {
                "input": {
                    "projectId": project_id,
                    "contentId": issue_graphql_id
                }
            }

            response = requests.post(
                graphql_url,
                json={"query": add_item_mutation, "variables": variables},
                headers=headers
            )

            if response.status_code != 200 or 'errors' in response.json():
                print(f"Failed to add issue #{issue.number} to project: {response.text}")
                continue

            print(f"Issue #{issue.number} in {repo.name} added to project.")

except RateLimitExceededException as e:
    reset_time = datetime.fromtimestamp(g.rate_limiting_resettime)
    print(f"Rate limit exceeded. Resets at {reset_time}.")
except Exception as e:
    print(f"An unexpected error occurred: {e}")
finally:
    if os.path.exists(lock_file):
        os.remove(lock_file)

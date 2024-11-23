import os
import re
import time
import sys
import requests
from datetime import datetime, timedelta
from github import GithubIntegration, Github
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

# Initialize a GitHubIntegration instance with your App ID and private key
integration = GithubIntegration(app_id, private_key)

# Fetch the installation for your organization
try:
    installation = integration.get_installation(owner=org_name)
    installation_id = installation.id
except GithubException as e:
    print(f"Failed to get installation for organization {org_name}: {e.data}")
    sys.exit(1)

# Generate an access token for the installation
try:
    access_token = integration.get_access_token(installation_id).token
except GithubException as e:
    print(f"Failed to get access token: {e.data}")
    sys.exit(1)

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

if response.status_code != 200:
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
    since_time = datetime.utcnow() - timedelta(days=1, minutes=5)
    since_time_iso = since_time.isoformat() + 'Z'

    # Fetch all repositories within the organization
    g = Github(access_token)
    org = g.get_organization(org_name)
    repos = org.get_repos()

    for repo in repos:
        if repo.archived or repo.fork or not repo.has_issues:
            continue

        # Fetch issues created since 'since_time'
        issues = repo.get_issues(state='open', since=since_time)

        for issue in issues:
            if issue.pull_request is not None:
                continue

            if issue.created_at < since_time:
                continue

            labels = [label.name for label in issue.labels]
            if 'DoNotAddToProject' in labels:
                continue

            # Check if the issue is already in the project
            # Since Projects (Beta) doesn't have columns like classic projects, we'll add the issue directly

            # GraphQL query to check if the issue is already in the project
            check_item_query = """
            query($projectId: ID!, $contentId: ID!) {
              node(id: $projectId) {
                ... on ProjectV2 {
                  items(first: 100, query: "", contentIds: [$contentId]) {
                    nodes {
                      id
                    }
                  }
                }
              }
            }
            """

            variables = {
                "projectId": project_id,
                "contentId": issue.node_id
            }

            response = requests.post(
                graphql_url,
                json={"query": check_item_query, "variables": variables},
                headers=headers
            )

            if response.status_code != 200:
                print(f"GraphQL query failed: {response.text}")
                continue

            items = response.json().get("data", {}).get("node", {}).get("items", {}).get("nodes", [])
            if items:
                # Issue is already in the project
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
                    "contentId": issue.node_id
                }
            }

            response = requests.post(
                graphql_url,
                json={"query": add_item_mutation, "variables": variables},
                headers=headers
            )

            if response.status_code != 200:
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

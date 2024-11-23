import os
import re
import time
import sys
import requests
from datetime import datetime, timedelta, timezone
from github import GithubIntegration, Github, Auth
from github.GithubException import GithubException, RateLimitExceededException

# [Configuration Variables and Authentication remain unchanged]

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

            # Optionally, comment out the following block to process all issues
            # if issue.created_at < since_time:
            #     print(f"Issue #{issue.number} was created before since_time. Skipping.")
            #     continue

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
            query($projectId: ID!, $contentId: ID!) {
              node(id: $projectId) {
                ... on ProjectV2 {
                  itemByContent(contentId: $contentId) {
                    id
                  }
                }
              }
            }
            """

            variables = {
                "projectId": project_id,
                "contentId": issue_graphql_id
            }

            response = requests.post(
                graphql_url,
                json={"query": check_item_query, "variables": variables},
                headers=headers
            )

            if response.status_code != 200 or 'errors' in response.json():
                print(f"GraphQL query failed: {response.text}")
                continue

            item_data = response.json().get("data", {}).get("node", {}).get("itemByContent")
            if item_data:
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

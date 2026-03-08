import requests
import json

class GitHubClient:
    def __init__(self, token=None):
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'Tocket CLI'
        })
        if token:
            self.session.headers.update({'Authorization': f'token {token}'})

    def validate_token(self):
        try:
            response = self.session.get('https://api.github.com/user')
            response.raise_for_status()
            user_data = response.json()
            scopes = response.headers.get('X-OAuth-Scopes', '').split(', ')
            return {
                'username': user_data.get('login'),
                'scopes': scopes
            }
        except requests.RequestException as e:
            print(f"Error validating token: {e}")
            return None

    def list_repos(self):
        try:
            response = self.session.get('https://api.github.com/user/repos')
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise Exception(f"Failed to list repos: {e}")

    def list_user_public_repos(self, username):
        try:
            response = self.session.get(f'https://api.github.com/users/{username}/repos')
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise Exception(f"Failed to list public repos for {username}: {e}")

    def get_repo(self, owner, repo):
        try:
            response = self.session.get(f'https://api.github.com/repos/{owner}/{repo}')
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise Exception(f"Failed to get repo {owner}/{repo}: {e}")

    def get_default_branch(self, owner, repo):
        repo_data = self.get_repo(owner, repo)
        return repo_data.get('default_branch')

    def create_repo(self, name, description=None, private=False, auto_init=False, gitignore_template=None, license_template=None):
        payload = {
            'name': name,
            'description': description,
            'private': private,
            'auto_init': auto_init
        }
        if gitignore_template:
            payload['gitignore_template'] = gitignore_template
        if license_template:
            payload['license_template'] = license_template
        try:
            response = self.session.post('https://api.github.com/user/repos', json=payload)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise Exception(f"Failed to create repo: {e}")

    def delete_repo(self, owner, repo):
        try:
            response = self.session.delete(f'https://api.github.com/repos/{owner}/{repo}')
            response.raise_for_status()
        except requests.RequestException as e:
            raise Exception(f"Failed to delete repo {owner}/{repo}: {e}")

    def patch_repo(self, owner, repo, payload):
        try:
            response = self.session.patch(f'https://api.github.com/repos/{owner}/{repo}', json=payload)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise Exception(f"Failed to patch repo {owner}/{repo}: {e}")

    def get_gitignore_templates(self):
        try:
            response = self.session.get('https://api.github.com/gitignore/templates')
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise Exception(f"Failed to get gitignore templates: {e}")

    def get_license_templates(self):
        try:
            response = self.session.get('https://api.github.com/licenses')
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise Exception(f"Failed to get license templates: {e}")

    def create_or_update_file(self, owner, repo, path, content, message, branch='main'):
        import base64
        encoded_content = base64.b64encode(content).decode('utf-8')
        payload = {
            'message': message,
            'content': encoded_content,
            'branch': branch
        }
        try:
            existing = self.get_contents(owner, repo, path, ref=branch)
            if existing:
                payload['sha'] = existing.get('sha')
        except Exception:
            pass
        try:
            response = self.session.put(f'https://api.github.com/repos/{owner}/{repo}/contents/{path}', json=payload)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise Exception(f"Failed to create/update file {path}: {e}")

    def delete_file(self, owner, repo, path, message, branch='main'):
        contents = self.get_contents(owner, repo, path, ref=branch)
        if not contents:
            raise FileNotFoundError(f"File {path} not found")
        payload = {
            'message': message,
            'sha': contents.get('sha'),
            'branch': branch
        }
        try:
            response = self.session.delete(f'https://api.github.com/repos/{owner}/{repo}/contents/{path}', json=payload)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise Exception(f"Failed to delete file {path}: {e}")

    def list_repo_tree(self, owner, repo, branch='main'):
        try:
            response = self.session.get(f'https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1')
            response.raise_for_status()
            data = response.json()
            return data.get('tree', [])
        except requests.RequestException as e:
            raise Exception(f"Failed to list tree for {owner}/{repo}: {e}")

    def get_contents(self, owner, repo, path, ref='main'):
        try:
            response = self.session.get(f'https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}')
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise Exception(f"Failed to get contents {path}: {e}")

    def list_workflows(self, owner, repo):
        try:
            response = self.session.get(f'https://api.github.com/repos/{owner}/{repo}/actions/workflows')
            response.raise_for_status()
            data = response.json()
            return data.get('workflows', [])
        except requests.RequestException as e:
            raise Exception(f"Failed to list workflows: {e}")

    def trigger_workflow(self, owner, repo, workflow_id, ref):
        url = f'https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches'
        payload = {'ref': ref}
        try:
            response = self.session.post(url, json=payload)
            response.raise_for_status()
        except requests.RequestException as e:
            raise Exception(f"Failed to trigger workflow: {e}")
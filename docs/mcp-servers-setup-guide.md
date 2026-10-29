# Claude Code MCP Servers - Setup Guide

This document describes the MCP (Model Context Protocol) servers available for Claude Code in our team's setup. Each section covers what the MCP does, example prompts you can use with it, and the installation command to add it to your Claude Code configuration.

## Table of Contents

- [ReportPortal](#reportportal)
- [Jira](#jira)
- [GitHub](#github)
- [Kubernetes](#kubernetes)
- [Jenkins](#jenkins)
- [Serena (Plugin)](#serena-plugin)
- [Must-Gather](#must-gather)

---

## ReportPortal

### What It Does

The ReportPortal MCP connects Claude to the team's ReportPortal instance, giving it the ability to query test launches, drill into individual test items, read failure logs and attachments, and manage defect classifications. This is the primary entry point for test failure analysis - Claude can list recent launches, filter test items by status or name, fetch detailed logs for failed tests, run auto-analysis or unique error analysis on a launch, and update defect types for test items.

### Example Prompts

- "Show me the last 5 launches for the OCS project."
- "Find all failed tests in launch 12345 that contain 'mcg' in the name."
- "Run unique error analysis on launch 12345."

### Installation

```bash
claude mcp add reportportal \
  -s user \
  -e RP_API_TOKEN="<YOUR_RP_API_TOKEN>" \
  -e RP_HOST="https://reportportal-ocs4.apps.dno.ocphub.prod.psi.redhat.com" \
  -e RP_PROJECT="OCS" \
  -- \
  podman run -i --rm \
  -v "<PATH_TO_YOUR_CA_PEM>:/etc/ssl/certs/ca.pem:ro" \
  -e RP_API_TOKEN \
  -e RP_HOST \
  -e RP_PROJECT \
  -e "CURL_CA_BUNDLE=/etc/ssl/certs/ca.pem" \
  -e "SSL_CERT_FILE=/etc/ssl/certs/ca.pem" \
  reportportal/mcp-server
```

### Notes

Runs as a Podman container. You need to provide a CA certificate PEM file for SSL verification with the internal ReportPortal instance. You also need a ReportPortal API token, which you can generate from your ReportPortal user profile.

---

## Jira

### What It Does

The Jira MCP gives Claude full access to the Red Hat Jira instance (Atlassian Cloud). Claude can search for issues, read epics and stories to understand feature requirements and acceptance criteria, file new bugs, add comments, transition issue statuses, manage versions and components, and create bug reports. This is especially useful for understanding the context behind test failures (checking if a bug is already known), filing new DFBUGS bugs with proper fields, and verifying fixed bugs by adding ON_QA verification comments.

### Example Prompts

- "Search DFBUGS for open bugs mentioning 'noobaa backingstore'."
- "Read epic DFBUGS-1234 and summarize the acceptance criteria."
- "File a bug in DFBUGS for this failure with the details we found."
- "Add a verification comment to DFBUGS-5678 with the build number and evidence."

### Installation

```bash
claude mcp add jira \
  -s user \
  -e JIRA_URL="https://redhat.atlassian.net" \
  -e JIRA_USERNAME="<YOUR_EMAIL>@redhat.com" \
  -e JIRA_API_TOKEN="<YOUR_JIRA_API_TOKEN>" \
  -- \
  uvx mcp-atlassian
```

### Notes

Requires a Jira API token from your Atlassian account. Generate one at https://id.atlassian.com/manage-profile/security/api-tokens. Use your Red Hat email as the username.

---

## GitHub

### What It Does

The GitHub MCP connects Claude to the GitHub platform, allowing it to search code, list and search pull requests and issues, read file contents from repositories, create and review PRs, manage branches, and inspect commits. This is useful for tracing test regressions to specific PRs, reviewing code changes that might have introduced a bug, searching across repositories for specific code patterns, and managing your own PRs (creating, updating, adding reviewers).

### Example Prompts

- "Search ocs-ci for recent PRs that modified the MCG bucket replication code."
- "Show me the diff for PR #15886 in red-hat-storage/ocs-ci."
- "Find all code in noobaa-core that references 'endpoint_monitor'."
- "Create a PR for my current branch with a summary of the changes."

### Installation

```bash
claude mcp add-json github -s user \
  '{"type":"http","url":"https://api.githubcopilot.com/mcp",\
  "headers":{"Authorization":"Bearer <GITHUB_API_TOKEN>"}}'
```

### Notes

Uses the GitHub Copilot MCP endpoint. You need a GitHub personal access token (classic) with appropriate scopes (repo, read:org). Generate one at GitHub Settings > Developer settings > Personal access tokens.

---

## Kubernetes

### What It Does

The Kubernetes MCP gives Claude read-only access to an OpenShift/Kubernetes cluster via its kubeconfig. Claude can list and inspect pods, read pod logs, check node stats and resource usage, list events and namespaces, and get any Kubernetes resource by kind and name. This is invaluable for live cluster debugging - checking if pods are healthy, reading operator logs, inspecting CRD statuses, and verifying that deployments are running as expected. The server runs in read-only mode for safety.

### Example Prompts

- "List all pods in the openshift-storage namespace and check their status."
- "Get the logs from the noobaa-operator pod for the last 100 lines."
- "Show me the NooBaa CR status in the openshift-storage namespace."
- "What events happened in the openshift-storage namespace in the last 10 minutes?"

### Installation

```bash
claude mcp add-json kubernetes-mcp-server \
  '{"command":"npx",\
  "args":["-y","kubernetes-mcp-server@latest","--readonly"],\
  "env":{"KUBECONFIG":"<PATH_TO_YOUR_KUBECONFIG>"}}' \
  -s user
```

### Notes

Requires Node.js/npx installed. Point the KUBECONFIG environment variable to your cluster's kubeconfig file (e.g., `~/cluster_path/auth/kubeconfig`). The `--readonly` flag ensures Claude cannot modify cluster state without your permission. To switch clusters, update the KUBECONFIG path and restart the MCP.

---

## Jenkins

### What It Does

The Jenkins MCP connects Claude to the team's Jenkins CI/CD server, allowing it to list jobs, inspect build history, read console output and test reports, view build parameters, check queue status, and (for approved jobs only) trigger new builds. This is useful for checking the status of deployment or test jobs, reading build logs to debug CI failures, and triggering PR verification jobs against test clusters.

### Example Prompts

- "What's the status of the latest qe-deploy-ocs-cluster build?"
- "Show me the console output for build #456 of qe-trigger-test-pr."
- "List all running builds on Jenkins right now."
- "Trigger qe-trigger-test-pr for PR #123 on cluster my-cluster."

### Installation

```bash
claude mcp add jenkins \
  -s user \
  -e JENKINS_URL="<YOUR_JENKINS_URL>" \
  -e JENKINS_USERNAME="<YOUR_JENKINS_USERNAME>" \
  -e JENKINS_API_TOKEN="<YOUR_JENKINS_API_TOKEN>" \
  -- \
  uvx mcp-jenkins
```

### Notes

Requires a Jenkins API token. Generate one from your Jenkins user profile under Configure > API Token. Write operations (triggering builds, stopping builds) should be restricted to approved jobs only.

---

## Serena (Plugin)

### What It Does

Serena is a code navigation plugin that provides language-aware tools for exploring Python codebases. Unlike basic grep or file search, Serena understands code structure - it can find symbol definitions (functions, classes, methods), locate all references to a symbol, list the symbols overview of a module, rename symbols safely across the codebase, and perform precise edits by replacing symbol bodies. This makes it the preferred tool for code-structural queries over grep-based approaches.

### Example Prompts

- "Find the definition of the function 'create_backingstore' and show me its body."
- "What classes and functions are defined in the mcg helpers module?"
- "Who calls the 'check_data_integrity' function?"
- "Rename the method 'old_name' to 'new_name' across the codebase."

### Installation

Serena is installed as a Claude Code plugin. Follow the Serena plugin installation instructions from the plugin registry.

After installation, disable the auto-opening dashboard by running:

```bash
sed -i '' 's/^web_dashboard_open_on_launch:.*/web_dashboard_open_on_launch: false/' \
  ~/.serena/serena_config.yml
```

### Notes

By default, Serena opens a web dashboard on every new Claude Code session. The sed command above disables this behavior. Serena is especially valuable for Python projects where understanding symbol relationships matters more than raw text search.

---

## Must-Gather

### What It Does

The Must-Gather MCP lets Claude download and analyze OpenShift must-gather archives directly from ReportPortal test failure logs. Must-gather bundles contain a snapshot of the cluster state at the time of failure - pod logs, Kubernetes events, resource YAMLs, and Ceph status - which are essential for root-cause analysis of test failures beyond what ReportPortal tracebacks alone can show. Claude can search pod logs for error patterns, inspect specific resources, read OCS-CI test execution logs from Magna, and cross-reference findings with an automated AI analysis report.

### Example Prompts

- "Download the must-gather from this RP failure and check the Ceph health status."
- "Search the noobaa-core pod logs for 'ECONNREFUSED' errors around the time of failure."
- "Get the OCS-CI test log for test_bucket_replication from this ReportPortal URL and tell me what happened step by step."
- "What does the AI analysis report say about this failure? Compare it with your own findings."

### Installation

```bash
claude mcp add must-gather \
  -s user \
  -e RP_API_KEY="<YOUR_RP_API_TOKEN>" \
  -e RP_BASE_URL="https://reportportal-ocs4.apps.dno.ocphub.prod.psi.redhat.com" \
  -e RP_SSL_VERIFY="false" \
  -- \
  uvx --from "git+https://github.com/sagihirshfeld/must-gather-downloader" \
  must-gather-downloader
```

### Notes

Requires a ReportPortal API token, which you can generate from your ReportPortal user profile. The MCP uses this token both to locate must-gather download URLs in RP logs and to authenticate with the RP instance.

This tool was built by Sagi Hirshfeld: https://github.com/sagihirshfeld/must-gather-downloader

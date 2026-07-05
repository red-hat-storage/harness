---
name: image-contains
description: "Check whether a container image includes the commit from a GitHub PR.
  Use when the developer says 'does the image contain', 'is the PR included',
  'check image for PR', or 'verify fix in image'."
version: "1.0"
type: skill
triggers:
  - "does the image contain"
  - "is the PR included"
  - "check image for PR"
  - "verify fix in image"
  - "image contains"
---

# Image Contains

Check whether a container image includes the commit from a GitHub PR by inspecting image labels and comparing Git commits via the GitHub API.

## Usage

```
/image-contains <image> <pr-url>
```

**Arguments** (passed as `$ARGUMENTS`, space-separated):

- First argument: full container image reference (e.g. `quay.io/rhceph-dev/ocs-registry:latest-stable-4.22.0`)
- Second argument: GitHub PR URL (e.g. `https://github.com/red-hat-storage/ocs-operator/pull/3990`)

## Prerequisites

- `gh` CLI authenticated with GitHub
- `oc` CLI with access to an OpenShift cluster (for pull-secret extraction)
- `skopeo` installed locally

## Steps

### 1. Parse arguments (no tool calls)

- Split `$ARGUMENTS` into IMAGE (first token) and PR_URL (second token).
- Extract OWNER and REPO from PR_URL pattern `https://github.com/<OWNER>/<REPO>/pull/<NUMBER>`.

### 2. Get PR info + cluster pull-secret (PARALLEL — two Bash calls in one message)

a. **PR info:**
   ```
   gh pr view <PR_URL> --json mergeCommit,mergedAt,state,title
   ```
   If state is not MERGED, report that and stop.

b. **Cluster pull-secret:**
   ```
   oc get secret pull-secret -n openshift-config \
     -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d > /tmp/ic-pull-secret.json
   ```

### 3. Inspect the image for upstream-vcs-ref

**Try direct inspection first:**
```
skopeo inspect --authfile /tmp/ic-pull-secret.json \
  --override-arch amd64 --override-os linux docker://<IMAGE> 2>&1
```

If successful and `.Labels["upstream-vcs-ref"]` is non-empty, skip to step 4.

**Otherwise it's a catalog/index image — extract operator image from catalog:**

a. Extract only the `/configs` directory (small, JSON-only — avoids downloading OS libraries):
   ```
   rm -rf /tmp/ic-extract && mkdir -p /tmp/ic-extract/configs/<REPO> && \
   oc image extract <IMAGE> -a /tmp/ic-pull-secret.json \
     --path /configs/<REPO>:/tmp/ic-extract/configs/<REPO> --confirm
   ```
   If that `--path` fails (source directory not found inside the image), retry with `--path /configs:/tmp/ic-extract/configs`.
   Then find REPO among the extracted directories: `ls /tmp/ic-extract/configs/`

b. Find the latest bundle:
   ```
   ls /tmp/ic-extract/configs/<REPO>/bundles/ | sort -V | tail -1
   ```

c. Extract `containerImage` from the bundle JSON:
   ```
   python3 -c "
   import json
   with open('/tmp/ic-extract/configs/<REPO>/bundles/<BUNDLE_FILE>') as f:
       data = json.load(f)
   for prop in data.get('properties', []):
       if prop.get('type') == 'olm.csv.metadata':
           meta = json.loads(prop['value']) if isinstance(prop['value'], str) else prop['value']
           print(meta['annotations']['containerImage'])
           break
   "
   ```
   This gives something like `registry.redhat.io/odf4/ocs-rhel9-operator@sha256:abc123...`

d. Construct the `quay.io/rhceph-dev` mirror URL (standard Konflux/CPaaS convention):
   - Parse `registry.redhat.io/<namespace>/<image-name>@sha256:...`
   - Mirror: `quay.io/rhceph-dev/<namespace>-<image-name>@sha256:...`
   - Example: `registry.redhat.io/odf4/ocs-rhel9-operator@sha256:abc` becomes `quay.io/rhceph-dev/odf4-ocs-rhel9-operator@sha256:abc`

e. Inspect the mirrored operator image:
   ```
   skopeo inspect --authfile /tmp/ic-pull-secret.json \
     --override-arch amd64 --override-os linux docker://<MIRROR_REF>
   ```
   If this fails, try the original `registry.redhat.io` reference, then `brew.registry.redhat.io`.

### 4. Check if PR is included (GitHub API — no git clone needed)

Extract `upstream-vcs-ref` and `build-date` from the skopeo JSON labels.

If PR merge commit SHA equals `upstream-vcs-ref`, it is an exact match and the PR is included.

Otherwise, use the GitHub compare API:
```
gh api repos/<OWNER>/<REPO>/compare/<upstream-vcs-ref>...<pr-merge-commit> --jq '.status'
```

Interpret the result:
- `"behind"` — PR commit is behind image commit — **PR IS included** (ancestor)
- `"identical"` — same commit — **PR IS included**
- `"ahead"` — PR commit is ahead of image commit — **PR is NOT included** (image is older)
- `"diverged"` — different branches — check if the PR was cherry-picked to the release branch via a separate PR. Use `gh pr list` to search for related PRs on the release branch and repeat the comparison with the cherry-pick merge commit.

### 5. Report result

Present a clear summary table with:
- PR title, merge commit SHA (short), and merge timestamp
- Image `upstream-vcs-ref` (short), `build-date`, `version`
- Whether the PR is included, with evidence (exact match / ancestor / not included)

### 6. Cleanup
```
rm -f /tmp/ic-pull-secret.json && rm -rf /tmp/ic-extract
```

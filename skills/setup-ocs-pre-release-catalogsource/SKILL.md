---
name: setup-dev-catalogsource
description: Set up a dev CatalogSource for pre-release ODF builds from quay.io/rhceph-dev/ocs-registry
argument-hint: <odf-version> [specific-tag]
---

# Set Up Dev CatalogSource

Set up an OpenShift cluster to use a pre-release ODF build from the dev registry (`quay.io/rhceph-dev/ocs-registry`). Disables the default `redhat-operators` CatalogSource, extracts and applies the IDMS from the catalog image, waits for MachineConfigPools to update, and creates a custom CatalogSource pointing to the dev build.

**Input:** `$ARGUMENTS`

Parse the arguments:
- First argument: ODF minor version (e.g., `4.22`, `4.18`)
- Second argument (optional): specific tag (e.g., `4.22.0-73.konflux`). If not provided, resolve the latest stable tag automatically in Step 2.

## Prerequisites

- `oc` logged into the target OpenShift cluster with cluster-admin privileges
- Cluster must be connected (not disconnected/air-gapped)

## Defaults (override if user specifies otherwise)

- **Registry**: `quay.io/rhceph-dev/ocs-registry`
- **CatalogSource name**: `redhat-operators`
- **CatalogSource namespace**: `openshift-marketplace`

## Step 1: Pre-flight checks

Run these checks in parallel using the Kubernetes MCP:

1. **Cluster access**: use `namespaces_list` to verify the cluster is reachable
2. **Existing CatalogSource**: use `resources_get` with `apiVersion: operators.coreos.com/v1alpha1`, `kind: CatalogSource`, `name: redhat-operators`, `namespace: openshift-marketplace` to check if it exists and what image it currently points to
3. **OperatorHub config**: run `oc get operatorhub.config.openshift.io/cluster -o jsonpath='{.spec.sources}'` to check if `redhat-operators` is already disabled

Report what was found. If a dev CatalogSource already exists (image contains `rhceph-dev/ocs-registry`), warn the user and ask whether to proceed or skip.

## Step 2: Resolve the image tag

If the user provided a specific tag, use it directly: `quay.io/rhceph-dev/ocs-registry:{specific-tag}`

If no specific tag was provided, resolve `latest-stable-{version}` to a concrete build tag using the Quay API. Run this as a single bash invocation so variables are preserved:

```
VERSION={version}
FLOATING_TAG_JSON=$(curl -s "https://quay.io/api/v1/repository/rhceph-dev/ocs-registry/tag/?specificTag=latest-stable-${VERSION}&onlyActiveTags=true")
DIGEST=$(echo "$FLOATING_TAG_JSON" | python3 -c "import sys,json; tags=json.load(sys.stdin)['tags']; print(tags[0]['manifest_digest'] if tags else '')")

if [ -z "$DIGEST" ]; then
  echo "ERROR: No floating tag found for latest-stable-${VERSION}"
  exit 1
fi

CONCRETE_TAGS_JSON=$(curl -s "https://quay.io/api/v1/repository/rhceph-dev/ocs-registry/tag/?onlyActiveTags=true&limit=20&filter_tag_name=like:${VERSION}.0-")
CONCRETE_TAG=$(echo "$CONCRETE_TAGS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
digest = '$DIGEST'
for tag in data['tags']:
    name = tag['name']
    if tag['manifest_digest'] == digest and not name.startswith('v') and 'latest' not in name:
        print(name)
        break
")

if [ -n "$CONCRETE_TAG" ]; then
  echo "Resolved: latest-stable-${VERSION} -> ${CONCRETE_TAG}"
else
  CONCRETE_TAG="latest-stable-${VERSION}"
  echo "Could not resolve concrete tag, using floating tag: ${CONCRETE_TAG}"
fi
```

Report the resolved tag to the user before proceeding.

## Step 3: Disable the default redhat-operators CatalogSource

Skip this step if pre-flight checks showed it is already disabled.

```
oc patch operatorhub.config.openshift.io/cluster --type=merge \
  -p '{"spec":{"sources":[{"disabled":true,"name":"redhat-operators"}]}}'
```

Wait 20 seconds after patching for the change to propagate.

## Step 4: Extract and apply IDMS from the catalog image

The catalog image may contain an `/idms.yaml` with ImageDigestMirrorSet rules. Extract and apply in a **single bash invocation** to avoid losing the temp directory:

```
TMPDIR=$(mktemp -d) && \
oc image extract --filter-by-os linux/amd64 \
  quay.io/rhceph-dev/ocs-registry:{resolved-tag} \
  --confirm \
  --path /idms.yaml:$TMPDIR && \
if [ -f "$TMPDIR/idms.yaml" ]; then
  echo "IDMS found, applying..." && \
  oc apply -f "$TMPDIR/idms.yaml" && \
  echo "IDMS applied successfully"
else
  echo "No IDMS found in catalog image — skipping"
fi
```

**Critical**: This must be a single bash invocation. Do NOT split the extract and apply into separate tool calls.

Note whether the IDMS was applied — this determines whether Step 5 is needed.

## Step 5: Wait for MachineConfigPools to update

**Skip this step if no IDMS was applied in Step 4.**

IDMS changes trigger a MachineConfig rollout that reboots nodes. Wait for both worker and master pools to finish updating:

```
echo "Waiting 60s for MCP update to begin..." && sleep 60

for pool in master worker; do
  echo "Waiting for MachineConfigPool/$pool..."
  for attempt in $(seq 1 60); do
    MACHINE_COUNT=$(oc get mcp $pool -o jsonpath='{.status.machineCount}')
    READY_COUNT=$(oc get mcp $pool -o jsonpath='{.status.readyMachineCount}')
    UPDATED_COUNT=$(oc get mcp $pool -o jsonpath='{.status.updatedMachineCount}')
    UPDATING=$(oc get mcp $pool -o jsonpath='{.status.conditions[?(@.type=="Updating")].status}')
    echo "  $pool: $READY_COUNT/$MACHINE_COUNT ready, $UPDATED_COUNT/$MACHINE_COUNT updated (attempt $attempt/60)"
    if [ "$READY_COUNT" = "$MACHINE_COUNT" ] && [ "$UPDATED_COUNT" = "$MACHINE_COUNT" ] && [ "$UPDATING" != "True" ]; then
      echo "  MachineConfigPool/$pool is ready"
      break
    fi
    if [ "$attempt" = "60" ]; then
      echo "  WARNING: MachineConfigPool/$pool did not finish within 30 minutes"
    fi
    sleep 30
  done
done
echo "All MachineConfigPools updated"
```

This step can take 15-30 minutes. Use a bash timeout of 600000ms (10 minutes). If the timeout is reached, report current MCP status and let the user decide whether to wait longer.

## Step 6: Create the dev CatalogSource

Apply the full CatalogSource YAML including `grpcPodConfig` with `extractContent` and `updateStrategy` with `registryPoll`:

```
oc apply -f - <<'EOF'
apiVersion: operators.coreos.com/v1alpha1
kind: CatalogSource
metadata:
  name: redhat-operators
  namespace: openshift-marketplace
  labels:
    ocs-operator-internal: "true"
spec:
  displayName: Openshift Container Storage
  image: quay.io/rhceph-dev/ocs-registry:{resolved-tag}
  publisher: Red Hat
  sourceType: grpc
  priority: 100
  grpcPodConfig:
    memoryTarget: 512Mi
    extractContent:
      cacheDir: /tmp/cache
      catalogDir: /configs
  updateStrategy:
    registryPoll:
      interval: 15m
EOF
```

Replace `{resolved-tag}` with the tag from Step 2.

## Step 7: Wait for CatalogSource to become READY

Poll the CatalogSource status until it reaches the READY state:

```
for i in $(seq 1 60); do
  STATE=$(oc get catalogsource redhat-operators -n openshift-marketplace \
    -o jsonpath='{.status.connectionState.lastObservedState}' 2>/dev/null)
  echo "Attempt $i/60: state=$STATE"
  if [ "$STATE" = "READY" ]; then
    echo "CatalogSource is READY"
    break
  fi
  if [ "$i" = "60" ]; then
    echo "WARNING: CatalogSource did not reach READY state within 10 minutes"
  fi
  sleep 10
done
```

After READY, use Kubernetes MCP `resources_get` to display the full CatalogSource resource for verification.

## Summary output

After completion, print:

```
Dev CatalogSource Setup Complete:
  Registry Image:  quay.io/rhceph-dev/ocs-registry:{resolved-tag}
  Tag Resolution:  latest-stable-{version} -> {resolved-tag}
  CatalogSource:   redhat-operators (openshift-marketplace)
  IDMS:            {Applied / Not found}
  MCP Update:      {Completed / Skipped}
  Status:          READY

To revert:
  oc delete catalogsource redhat-operators -n openshift-marketplace
  oc delete imagedigestmirrorset <idms-name>    # if IDMS was applied
  # Wait for MCPs to finish updating, then:
  oc patch operatorhub.config.openshift.io/cluster --type=merge \
    -p '{"spec":{"sources":[{"disabled":false,"name":"redhat-operators"}]}}'
```

## Notes

- The CatalogSource name `redhat-operators` replaces the default, which is why it must be disabled first.
- The `grpcPodConfig.extractContent` fields are required for the catalog pod to properly serve content — do not omit them.
- The `updateStrategy.registryPoll.interval: 15m` ensures the catalog picks up new pushes to floating tags.
- If the user provides a specific tag, skip the Quay API resolution entirely.
- Use `$ARGUMENTS` for the version and optional tag.

---
name: delete-df-storage
description: "Remove HCP clusters and Fusion Data Foundation (FDF/ODF) from an IBM
  Spectrum Fusion HCI cluster so FDF can be reinstalled with a different version.
  ISF and other Fusion services remain intact."
version: "1.0"
type: skill
triggers:
  - "delete df storage"
  - "uninstall fdf"
  - "remove odf"
  - "remove data foundation"
  - "clean fdf"
---

# Delete DF Storage

Remove HCP KubeVirt clusters and Fusion Data Foundation (FDF/ODF) from an IBM Spectrum Fusion HCI cluster so FDF can be reinstalled with a different version. ISF and all other Fusion services remain intact.

**This is a DESTRUCTIVE operation for storage data. It cannot be undone.**

## References

- Official doc: https://www.ibm.com/docs/en/fusion-hci-systems/2.13.0?topic=services-uninstalling-fusion-data-foundation
- Upstream script: https://github.ibm.com/ProjectAbell/fusion-runbooks/blob/main/tools/delete-fusion-odf.sh

## Prerequisites

- `oc` CLI logged in with cluster-admin
- `hypershift` CLI available (if HCP clusters exist)

## Steps

### 1. Pre-flight

Confirm with the user that this is destructive. Verify cluster identity:

```bash
oc whoami && oc cluster-info
```

Show the endpoint and ask the user to confirm it is the correct cluster.

Check for leftover test PVCs/OBCs that will cause the script to abort:

```bash
# List PVCs using ODF StorageClasses outside openshift-storage
oc get pvc -A --no-headers 2>/dev/null | grep -E "ceph|noobaa|rook" | grep -v openshift-storage

# List OBCs
oc get obc -A --no-headers 2>/dev/null
```

If any exist, clean them up:
- Delete test namespaces: `oc delete ns <namespace> --wait=false`
- Patch OBC finalizers: `oc get obc -n openshift-storage -o name | xargs -I{} oc patch {} -n openshift-storage --type merge -p '{"metadata":{"finalizers":[]}}' && oc delete obc --all -n openshift-storage`
- Delete noobaa internal PVC: `oc delete pvc noobaa-bucket-notifications-pvc -n openshift-storage`

### 2. Destroy HCP clusters (Phase 1, Step 0)

```bash
oc get hostedclusters -A
```

If any exist, destroy them **in parallel**:

```bash
hypershift destroy cluster kubevirt --name <cluster-1> --namespace clusters &
hypershift destroy cluster kubevirt --name <cluster-2> --namespace clusters &
wait
```

Wait for deletion to complete (10-15 min per cluster):

```bash
oc wait --for=delete hostedcluster/<name> -n clusters --timeout=15m
```

**Note**: `hypershift destroy` may report `context deadline exceeded` even though the cluster was deleted. Always verify with `oc get hostedclusters -A`.

If truly stuck, patch the finalizer off:
```bash
oc patch hostedcluster/<name> -n clusters --type merge -p '{"metadata":{"finalizers":[]}}'
oc delete ns clusters-<name> --wait=false
```

### 3. Scale down ISF and delete FDF resources (Phase 1, Steps 1-4)

**IMPORTANT**: Only scale down operators — do NOT delete ISF subscriptions, CSVs, or namespaces.

```bash
export FUSION_NS="ibm-spectrum-fusion-ns"

oc scale deployment isf-cns-operator-controller-manager -n "$FUSION_NS" --replicas=0

oc delete odfmanager odfmanager 2>/dev/null || true
oc delete odfcluster odfcluster -n "$FUSION_NS" 2>/dev/null || true

oc delete pvc isf-bkprstr-claim logcollector -n "$FUSION_NS" 2>/dev/null || true
```

### 4. Run the cleanup script (Phase 2)

Download and run the `delete-fusion-odf.sh` script from the [Fusion runbooks](https://github.ibm.com/ProjectAbell/fusion-runbooks):

```bash
curl -sSL -o /tmp/delete-df-storage.sh \
  https://raw.github.ibm.com/ProjectAbell/fusion-runbooks/main/tools/delete-fusion-odf.sh

bash /tmp/delete-df-storage.sh 2>&1 | tee /tmp/delete-df-storage-$(date +%Y%m%d-%H%M%S).log
```

The script runs 15 automated steps: StorageCluster annotation, PVC/OBC safety check, StorageConsumer/Client/System deletion, namespace cleanup with finalizer fallback, rook data cleanup, encrypted disk check, LSO cleanup, PV finalizer clearing, StorageClass deletion, node unlabeling, and operator removal.

### 5. Post-script namespace cleanup (often needed)

The namespace deletion often times out. After the script, check and fix:

```bash
oc get ns openshift-storage --no-headers 2>/dev/null
```

If still Terminating, check what's blocking:
```bash
oc get ns openshift-storage -o json | jq '.status.conditions[] | select(.status == "True") | {type, message}'
```

Common fixes (run in order):
1. Force-delete completed noobaa-db pods: `oc delete pod -n openshift-storage -l cnpg.io/cluster=noobaa-db-pg --force --grace-period=0`
2. Clear BackingStore/BucketClass finalizers: `patch_finalizers backingstores.noobaa.io openshift-storage && patch_finalizers bucketclasses.noobaa.io openshift-storage`
3. Clear OBC secret finalizers: `oc get secrets -n openshift-storage -o name | xargs -I{} oc patch {} -n openshift-storage --type merge -p '{"metadata":{"finalizers":[]}}'`
4. Clear Released PV finalizers: patch and delete any Released/Terminating PVs
5. Delete remaining noobaa SC: `oc delete sc openshift-storage.noobaa.io`

### 6. Restore ISF and prepare for redeployment (Phase 3)

```bash
export FUSION_NS="ibm-spectrum-fusion-ns"

# Delete old FDF catalog (scale down platform operator first to prevent auto-recreation)
oc scale deployment isf-platform-operator-controller-manager -n "$FUSION_NS" --replicas=0
oc delete catalogsource isf-data-foundation-catalog -n openshift-marketplace 2>/dev/null || true

# Delete orphaned Fusion management StorageClass
oc delete sc ibm-spectrum-fusion-mgmt-sc 2>/dev/null || true

# Recreate ISF internal PVCs (will be Pending until new FDF is deployed)
cat <<'PVCEOF' | oc apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: isf-bkprstr-claim
  namespace: ibm-spectrum-fusion-ns
spec:
  accessModes: [ReadWriteMany]
  resources:
    requests:
      storage: 25Gi
PVCEOF

cat <<'PVCEOF' | oc apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: logcollector
  namespace: ibm-spectrum-fusion-ns
spec:
  accessModes: [ReadWriteMany]
  resources:
    requests:
      storage: 25Gi
PVCEOF

# Scale ISF operators back up (EXCEPT platform operator if switching FDF version)
oc scale deployment isf-cns-operator-controller-manager -n "$FUSION_NS" --replicas=1
oc scale deployment isf-bkprstr-operator-controller-manager -n "$FUSION_NS" --replicas=1 2>/dev/null || true
oc scale deployment logcollector -n "$FUSION_NS" --replicas=2
```

**IMPORTANT**: Do NOT scale `isf-platform-operator-controller-manager` back to 1 until you are ready to install — it auto-recreates the FDF catalog and triggers reinstallation of the previous version.

To install a **different** ODF version, create the CatalogSource manually first:
```bash
cat <<'CSEOF' | oc apply -f -
apiVersion: operators.coreos.com/v1alpha1
kind: CatalogSource
metadata:
  name: isf-data-foundation-catalog
  namespace: openshift-marketplace
spec:
  displayName: Data Foundation Catalog
  image: icr.io/cpopen/isf-data-foundation-catalog:v4.21
  publisher: IBM
  sourceType: grpc
CSEOF
```

### 7. Final verification

FDF/ODF should be gone:
```bash
oc get ns openshift-storage openshift-local-storage 2>&1
oc get sc | grep -E "ceph|noobaa|ocs|openshift-storage|ibm-spectrum-fusion-mgmt"
oc get hostedclusters -A
oc get odfcluster -A
oc get odfmanager
```

ISF should still be healthy:
```bash
oc get ns ibm-spectrum-fusion-ns
oc get pods -n ibm-spectrum-fusion-ns | grep -E "isf-|logcollector"
oc get sub -n ibm-spectrum-fusion-ns
oc get csv -n ibm-spectrum-fusion-ns
oc get catalogsource fusion-catalog -n openshift-marketplace
```

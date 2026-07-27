#!/usr/bin/env bash
# delete-df-storage.sh
# Combined DF/ODF Storage uninstall script for IBM Spectrum Fusion HCI clusters.
# Handles stuck finalizers, PV cleanup, LSO cleanup, and operator removal.
#
# Usage: bash delete-df-storage.sh
# Prerequisites: oc logged in to target cluster with cluster-admin

set -u

RED='\033[91m'; GREEN='\033[92m'; YELLOW='\033[93m'; NORMAL='\033[0m'
INFO="$(echo -e "${GREEN}I${NORMAL}")"; WARNING="$(echo -e "${YELLOW}W${NORMAL}")"; ERROR="$(echo -e "${RED}E${NORMAL}")"

info()  { printf "$(date +"%T") [%s] %s\n" "$INFO" "$1"; }
warn()  { printf "$(date +"%T") [%s] %s\n" "$WARNING" "$1"; }
error() { printf "$(date +"%T") [%s] %s\n" "$ERROR" "$1"; }

# Remove all finalizers from every resource of a given type in a namespace
patch_finalizers() {
  local resource=$1 namespace=${2:-}
  local ns_flag=""
  [ -n "$namespace" ] && ns_flag="-n $namespace"
  local names
  names=$(oc get "$resource" $ns_flag -o name 2>/dev/null) || return 0
  [ -z "$names" ] && return 0
  echo "$names" | xargs -I{} oc patch {} $ns_flag --type merge -p '{"metadata":{"finalizers":[]}}' 2>/dev/null || true
  info "Cleared finalizers on $resource${namespace:+ in $namespace}"
}

echo
echo "================================================================="
echo "Uninstall DF Storage on Fusion HCI Cluster"
echo "================================================================="

# ── Step 1: StorageCluster forced-uninstall annotation ────────────────
printf "\n------[1] Annotate StorageCluster------\n"
result=$(oc get storagecluster -n openshift-storage --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [[ $result -eq 0 ]]; then
    info "No StorageCluster found, skipping"
else
    sc_name=$(oc get storagecluster -n openshift-storage -o name)
    oc annotate "$sc_name" -n openshift-storage uninstall.ocs.openshift.io/mode="forced" --overwrite
    info "StorageCluster annotated for forced uninstall"
fi

# ── Step 2: PVC / OBC safety check ────────────────────────────────────
printf "\n------[2] Check PVCs/OBCs------\n"
RBD_PROVISIONER="rbd.csi.ceph.com"
CEPHFS_PROVISIONER="cephfs.csi.ceph.com"
NOOBAA_PROVISIONER="noobaa.io/obc"
RGW_PROVISIONER="ceph.rook.io/bucket"
NOOBAA_DB_PVC="noobaa-db"
NOOBAA_BACKINGSTORE_PVC="noobaa-default-backing-store-noobaa-pvc"

OCS_STORAGECLASSES=$(oc get storageclasses 2>/dev/null \
  | grep -e "$RBD_PROVISIONER" -e "$CEPHFS_PROVISIONER" -e "$NOOBAA_PROVISIONER" -e "$RGW_PROVISIONER" \
  | awk '{print $1}')

has_pvc_obc=0
for SC in $OCS_STORAGECLASSES; do
    count=$(oc get pvc --all-namespaces --no-headers 2>/dev/null \
              | grep "$SC" \
              | grep -c -v -e "$NOOBAA_DB_PVC" -e "$NOOBAA_BACKINGSTORE_PVC" || true)
    if [[ $count -gt 0 ]]; then
        has_pvc_obc=1
        error "PVCs using $SC still exist:"
        oc get pvc --all-namespaces --no-headers 2>/dev/null \
          | grep "$SC" | grep -v -e "$NOOBAA_DB_PVC" -e "$NOOBAA_BACKINGSTORE_PVC"
    else
        info "No PVCs using $SC"
    fi
    count=$(oc get obc --all-namespaces --no-headers 2>/dev/null | grep -c "$SC" || true)
    if [[ $count -gt 0 ]]; then
        has_pvc_obc=1
        error "OBCs using $SC still exist:"
        oc get obc --all-namespaces --no-headers 2>/dev/null | grep "$SC"
    else
        info "No OBCs using $SC"
    fi
done
if [[ $has_pvc_obc -eq 1 ]]; then
    error "Remove PVCs/OBCs listed above first, then re-run this script."
    exit 1
fi
info "PVC/OBC check passed"

# ── Step 3: StorageConsumer ────────────────────────────────────────────
printf "\n------[3] Delete StorageConsumer------\n"
result=$(oc get storageconsumer -n openshift-storage --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [[ $result -eq 0 ]]; then
    info "No StorageConsumer found"
else
    # Pre-clear finalizers so --wait=true doesn't hang
    patch_finalizers "storageconsumer" "openshift-storage"
    oc delete storageconsumer --all -n openshift-storage --wait=true --timeout=2m 2>/dev/null \
      && info "StorageConsumer deleted" \
      || warn "StorageConsumer deletion timed out"
fi

# ── Step 4: StorageClient (clear storageclient.ocs.openshift.io finalizer) ──
printf "\n------[4] Delete StorageClient------\n"
result=$(oc get storageclient -A --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [[ $result -eq 0 ]]; then
    info "No StorageClient found"
else
    patch_finalizers "storageclient"
    oc delete storageclient --all --wait=true --timeout=2m 2>/dev/null \
      && info "StorageClient deleted" \
      || warn "StorageClient deletion timed out"
fi

# ── Step 5: StorageSystem (cascades to StorageCluster) ────────────────
printf "\n------[5] Delete StorageSystem------\n"
result=$(oc get storagesystem -n openshift-storage --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [[ $result -eq 0 ]]; then
    info "No StorageSystem found"
else
    oc delete storagesystem --all -n openshift-storage --wait=true --timeout=10m 2>/dev/null \
      && info "StorageSystem deleted" \
      || warn "StorageSystem deletion timed out — continuing"
fi

# ── Step 6: OCP version check (cleanup pods, OCP < 4.14 only) ─────────
printf "\n------[6] Check OCP version / cleanup pods------\n"
ocpversion=$(oc get clusterversion --no-headers 2>/dev/null | awk '{print $2}')
ocpversion_minor=$(echo "$ocpversion" | cut -d "." -f2)
if [[ ocpversion_minor -lt 14 ]]; then
    info "OCP $ocpversion: waiting 60s for cleanup pods"
    sleep 60
    completed=$(oc get pods -n openshift-storage 2>/dev/null | grep cluster-cleanup-job | grep -c Completed || true)
    total=$(oc get pods -n openshift-storage 2>/dev/null | grep -c cluster-cleanup-job || true)
    if [[ $total -gt 0 && $completed -lt $total ]]; then
        error "Not all cleanup jobs completed ($completed/$total). Wait and retry."
        exit 1
    fi
    info "Cleanup jobs done"
else
    info "OCP $ocpversion (≥ 4.14): skipping cleanup pod check"
fi

# ── Step 7: Delete openshift-storage namespace ────────────────────────
printf "\n------[7] Delete openshift-storage namespace------\n"
result=$(oc get ns openshift-storage --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [[ $result -eq 0 ]]; then
    info "openshift-storage namespace does not exist"
else
    oc project default 2>/dev/null
    oc delete ns openshift-storage --wait=true --timeout=5m 2>/dev/null
    if [[ $? -ge 1 ]]; then
        warn "Namespace deletion timed out — clearing stuck finalizers"

        # Ceph and ODF CRD finalizers
        for r in \
          cephblockpoolradosnamespaces.ceph.rook.io \
          cephblockpools.ceph.rook.io \
          cephclients.ceph.rook.io \
          cephclusters.ceph.rook.io \
          cephfilesystems.ceph.rook.io \
          cephfilesystemsubvolumegroups.ceph.rook.io \
          cephobjectstores.ceph.rook.io \
          cephobjectstoreusers.ceph.rook.io \
          clientprofiles.csi.ceph.io \
          csiaddonsnodes.csiaddons.openshift.io \
          noobaas.noobaa.io \
          backingstores.noobaa.io \
          bucketclasses.noobaa.io \
          storageclusters.ocs.openshift.io \
          storageconsumers.ocs.openshift.io; do
            patch_finalizers "$r" "openshift-storage"
        done

        # ConfigMap / Secret finalizers (includes OBC secrets with objectbucket.io/finalizer)
        for cm in ocs-client-operator-config rook-ceph-mon-endpoints; do
            oc patch configmap "$cm" -n openshift-storage \
              --type merge -p '{"metadata":{"finalizers":[]}}' 2>/dev/null || true
        done
        oc get secrets -n openshift-storage -o name 2>/dev/null \
          | xargs -I{} oc patch {} -n openshift-storage \
              --type merge -p '{"metadata":{"finalizers":[]}}' 2>/dev/null || true

        # Force-delete completed noobaa-db pods that block namespace termination
        oc delete pods -n openshift-storage -l cnpg.io/cluster=noobaa-db-pg \
          --force --grace-period=0 2>/dev/null || true

        info "Waiting up to 60s for namespace to terminate..."
        for i in {1..12}; do
            [[ $(oc get ns openshift-storage --no-headers 2>/dev/null | wc -l | tr -d ' ') -eq 0 ]] && break
            sleep 5
        done
    fi

    result=$(oc get ns openshift-storage --no-headers 2>/dev/null | wc -l | tr -d ' ')
    if [[ $result -eq 0 ]]; then
        info "openshift-storage namespace deleted"
    else
        warn "openshift-storage namespace still Terminating — may complete on its own"
    fi
fi

# ── Step 8: Clean /var/lib/rook on storage nodes ──────────────────────
printf "\n------[8] Clean /var/lib/rook on storage nodes------\n"
for node in $(oc get node -l cluster.ocs.openshift.io/openshift-storage= \
               -o jsonpath='{ .items[*].metadata.name }' 2>/dev/null); do
    info "Cleaning /var/lib/rook on $node"
    oc debug node/"$node" -- chroot /host rm -rf /var/lib/rook 2>/dev/null
done

# ── Step 9: Encrypted disk cleanup ────────────────────────────────────
printf '\n------[9] Check encrypted disks------\n'
info "Checking for encrypted disks..."
enc_result=$(for node in $(oc get node -l cluster.ocs.openshift.io/openshift-storage= \
                            -o jsonpath='{ .items[*].metadata.name }' 2>/dev/null); do
    oc debug node/"$node" -- chroot /host dmsetup ls 2>/dev/null
done)
if [[ $enc_result == *"dmcrypt"* ]]; then
    warn "Encrypted disks found — cleaning up"
    for node in $(oc get node -l cluster.ocs.openshift.io/openshift-storage= \
                   -o jsonpath='{ .items[*].metadata.name }' 2>/dev/null); do
        oc debug node/"$node" -- chroot /host dmsetup ls 2>/dev/null \
          | awk '{print $1}' \
          | xargs -I {} oc debug node/"$node" -- chroot /host cryptsetup luksClose --debug --verbose {} 2>/dev/null
    done
    info "Encrypted disk cleanup done"
else
    info "No encrypted disks found"
fi

# ── Step 10: LocalVolumeSet + LSO cleanup ─────────────────────────────
printf "\n------[10] Delete LocalVolumeSet and LSO------\n"
result=$(oc get localvolumeset -n openshift-local-storage --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [[ $result -eq 0 ]]; then
    info "No LocalVolumeSet found"
else
    # Pre-clear finalizers then delete
    patch_finalizers "localvolumesets.local.storage.openshift.io" "openshift-local-storage"
    oc delete localvolumesets.local.storage.openshift.io --all -n openshift-local-storage 2>/dev/null
    info "LocalVolumeSet deleted"

    # Delete only Available PVs from no-provisioner StorageClasses (skip Bound ones)
    sc_list=$(oc get sc 2>/dev/null | grep "kubernetes.io/no-provisioner" | awk '{print $1}')
    for sc in $sc_list; do
        pv_list=$(oc get pv --no-headers 2>/dev/null | grep "$sc" | grep "Available" | awk '{print $1}')
        if [ -n "$pv_list" ]; then
            echo "$pv_list" | xargs oc delete pv 2>/dev/null
            info "Deleted Available PVs for StorageClass $sc"
        fi
        oc delete sc "$sc" 2>/dev/null && info "Deleted StorageClass $sc" || true
    done

    # Delete symlinks on storage nodes
    for node in $(oc get node -l cluster.ocs.openshift.io/openshift-storage= \
                   -o jsonpath='{ .items[*].metadata.name }' 2>/dev/null); do
        oc debug node/"$node" -- chroot /host rm -rfv /mnt/local-storage/ 2>/dev/null
    done

    # Delete openshift-local-storage namespace
    result=$(oc get ns openshift-local-storage --no-headers 2>/dev/null | wc -l | tr -d ' ')
    if [[ $result -gt 0 ]]; then
        oc delete ns openshift-local-storage --wait=true --timeout=5m 2>/dev/null
        if [[ $? -ge 1 ]]; then
            warn "openshift-local-storage deletion timed out — fixing localvolumeset finalizers"
            patch_finalizers "localvolumesets.local.storage.openshift.io" "openshift-local-storage"
            sleep 15
        fi
        result=$(oc get ns openshift-local-storage --no-headers 2>/dev/null | wc -l | tr -d ' ')
        [[ $result -eq 0 ]] && info "openshift-local-storage namespace deleted" \
                             || warn "openshift-local-storage still Terminating"
    fi
fi

# ── Step 11: Clear stuck PV finalizers ────────────────────────────────
printf "\n------[11] Clear stuck PV finalizers------\n"
for pv in $(oc get pv --no-headers 2>/dev/null | grep -E "Terminating|Released" | awk '{print $1}'); do
    finalizers=$(oc get pv "$pv" -o jsonpath='{.metadata.finalizers}' 2>/dev/null)
    if [[ "$finalizers" == *"lso-symlink-deleter"* ]] \
    || [[ "$finalizers" == *"external-provisioner"* ]] \
    || [[ "$finalizers" == *"external-attacher"* ]]; then
        oc patch pv "$pv" --type merge -p '{"metadata":{"finalizers":[]}}' 2>/dev/null \
          && info "Cleared finalizers on PV $pv"
    fi
done

# ── Step 12: Delete remaining ODF StorageClasses ──────────────────────
printf "\n------[12] Delete ODF StorageClasses------\n"
odf_scs=$(oc get sc --no-headers 2>/dev/null \
  | grep -E "rbd\.csi\.ceph\.com|cephfs\.csi\.ceph\.com|ceph\.rook\.io|noobaa\.io" \
  | awk '{print $1}')
if [ -n "$odf_scs" ]; then
    echo "$odf_scs" | xargs oc delete sc 2>/dev/null && info "ODF StorageClasses deleted"
else
    info "No ODF StorageClasses remaining"
fi

# ── Step 13: Unlabel and untaint nodes ────────────────────────────────
printf "\n------[13] Unlabel/untaint nodes------\n"
oc label nodes --all cluster.ocs.openshift.io/openshift-storage- 2>/dev/null || true
oc label nodes --all topology.rook.io/rack- 2>/dev/null || true
oc adm taint nodes --all node.ocs.openshift.io/storage- 2>/dev/null || true
info "Node labels and taints removed"

# ── Step 14: Delete ODF operators (OdfCluster, OdfManager, FSI, Subs, CSVs) ──
printf "\n------[14] Delete ODF Operators------\n"
oc delete odfcluster --all -A 2>/dev/null && info "OdfCluster deleted" || true
oc delete odfmanager --all 2>/dev/null && info "OdfManager deleted" || true
oc delete fusionserviceinstance odfmanager -n ibm-spectrum-fusion-ns 2>/dev/null \
  && info "FusionServiceInstance/odfmanager deleted" || true
oc delete sub --all -n openshift-storage 2>/dev/null && info "Subscriptions deleted" || true
oc delete csv --all -n openshift-storage 2>/dev/null && info "CSVs deleted" || true

# ── Final state report ────────────────────────────────────────────────
printf "\n------[15] Final state------\n"
echo "--- PVs (Released/Available, non-Spectrum-Scale) ---"
oc get pv --no-headers 2>/dev/null \
  | grep -E "Released|Available" \
  | grep -v "ibm-spectrum-scale" \
  || echo "none"

echo "--- ODF namespaces ---"
oc get ns 2>/dev/null | grep -E "openshift-storage|openshift-local-storage" || echo "none"

echo "--- ODF StorageClasses ---"
oc get sc --no-headers 2>/dev/null | grep -E "ceph|noobaa|ocs|openshift-storage" || echo "none"

echo "--- CSVs in openshift-storage (non-ODF expected) ---"
oc get csv -n openshift-storage --no-headers 2>/dev/null \
  | grep -v -E "node-maintenance|self-node-remediation" \
  || echo "none (only infrastructure CSVs remain — OK)"

echo ""
echo "================================================================="
echo "DF Storage uninstall completed $(date +"%F %Z")"
echo "================================================================="

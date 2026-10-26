# REVIEW-ONLY candidate. NEVER install without scoped approval and rollback.
# Source: original Mochilab OpenBot pinned profile + scoped native Codex Lab.
# Mochilab OpenBot AppArmor container profile.
# Based on Docker's docker-default profile (Moby v28.3.3), with one additional
# permission: unprivileged user namespace creation for OpenBot's Electron sandbox.
# Loaded only under profile name 'mochilab-openbot'; docker-default is unchanged.
#include <tunables/global>

profile mochilab-openbot-workspace-candidate flags=(attach_disconnected,mediate_deleted) {
  #include <abstractions/base>

  network,
  capability,
  file,
  umount,
  userns create,

  signal (receive) peer=unconfined,
  signal (receive) peer=runc,
  signal (receive) peer=crun,
  signal (send,receive) peer=mochilab-openbot-workspace-candidate,

  deny @{PROC}/* w,
  deny @{PROC}/{[^1-9],[^1-9][^0-9],[^1-9s][^0-9y][^0-9s],[^1-9][^0-9][^0-9/]*}/** w,
  deny @{PROC}/sys/[^k]** w,
  deny @{PROC}/sys/kernel/{?,??,[^s][^h][^m]**} w,
  deny @{PROC}/sysrq-trigger rwklx,
  deny @{PROC}/kcore rwklx,

  mount options=(rw,rslave,silent) -> /,
  mount options=(rw,rprivate,silent) -> /oldroot/,
  mount options=(rw,rbind) /tmp/newroot/ -> /tmp/newroot/,
  mount options=(rw,rbind) /** -> /newroot/{,**},
  mount options=(rw,bind) /** -> /newroot/{,**},
  mount options=(rw,rbind) /oldroot/proc/ -> /proc/,
  mount fstype=tmpfs options=(rw,nosuid,nodev) tmpfs -> /tmp/,
  mount fstype=tmpfs options=(rw,nosuid,nodev) tmpfs -> /newroot/{,**},
  mount fstype=devpts options=(rw,nosuid,noexec) devpts -> /newroot/dev/pts/,
  mount fstype=proc options=(rw,nosuid,nodev,noexec) proc -> /newroot/proc/,
  remount /newroot/{,**},
  pivot_root oldroot=/tmp/oldroot/ /tmp/,
  pivot_root oldroot=/newroot/ /newroot/,

  deny /sys/[^f]*/** wklx,
  deny /sys/f[^s]*/** wklx,
  deny /sys/fs/[^c]*/** wklx,
  deny /sys/fs/c[^g]*/** wklx,
  deny /sys/fs/cg[^r]*/** wklx,
  deny /sys/firmware/** rwklx,
  deny /sys/devices/virtual/powercap/** rwklx,
  deny /sys/kernel/security/** rwklx,

  ptrace (trace,read,tracedby,readby) peer=mochilab-openbot-workspace-candidate,
}

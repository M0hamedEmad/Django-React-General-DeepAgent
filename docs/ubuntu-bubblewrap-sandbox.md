# Bubblewrap sandbox deployment on Ubuntu

This guide configures the Deep Agent `execute` tool on an Ubuntu production
server. It was verified on Ubuntu 24.04 LTS with Bubblewrap 0.9 and
slirp4netns 1.2.

The application uses:

- Bubblewrap for user, mount, PID, IPC, UTS, cgroup, and network namespaces.
- Read-only system, skill, and sibling-conversation mounts.
- A writable workspace for only the current conversation.
- `slirp4netns` for outbound network access without sharing the host network
  namespace.
- A conversation-local `.venv` for packages installed by the agent.

Do not run Django as root. Do not disable AppArmor globally, make Bubblewrap
setuid-root, or add `--share-net` to work around a namespace error.

## 1. Install operating-system packages

```bash
sudo apt-get update
sudo apt-get install -y \
  apparmor \
  apparmor-utils \
  bubblewrap \
  python3-venv \
  slirp4netns
```

Confirm that both executables are available:

```bash
bwrap --version
slirp4netns --version
```

## 2. Keep Bubblewrap non-setuid

The project uses unprivileged user namespaces. `/usr/bin/bwrap` must be owned
by root but must not have a setuid bit.

```bash
sudo dpkg-statoverride --remove /usr/bin/bwrap 2>/dev/null || true
sudo dpkg-statoverride --update --add root root 0755 /usr/bin/bwrap
stat -c '%U:%G %a %n' /usr/bin/bwrap
```

Expected result:

```text
root:root 755 /usr/bin/bwrap
```

The `dpkg-statoverride` entry preserves this mode when the Bubblewrap package
is upgraded.

## 3. Allow Bubblewrap user namespaces through AppArmor

Ubuntu 24.04 can restrict unprivileged user namespaces with AppArmor. Check
whether the restriction exists and is enabled:

```bash
sysctl kernel.apparmor_restrict_unprivileged_userns
```

If the command reports `kernel.apparmor_restrict_unprivileged_userns = 1`,
install this executable-specific profile:

```bash
sudo tee /etc/apparmor.d/deep-agent-bwrap >/dev/null <<'EOF'
abi <abi/4.0>,
include <tunables/global>

profile deep-agent-bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/deep-agent-bwrap>
}
EOF

sudo apparmor_parser -r /etc/apparmor.d/deep-agent-bwrap
sudo aa-status | grep deep-agent-bwrap
```

The exemption applies to `/usr/bin/bwrap`, not to the Django process or every
program on the server. Bubblewrap then applies the filesystem and namespace
isolation before it starts an agent command.

On an older Ubuntu release where the sysctl key does not exist, do not install
an AppArmor 4 profile blindly. First confirm that the distribution permits
unprivileged user namespaces and run the smoke test below.

## 4. Run a Bubblewrap smoke test

Run this as the same unprivileged Linux user that will run Django:

```bash
bwrap \
  --unshare-all \
  --die-with-parent \
  --new-session \
  --cap-drop ALL \
  --ro-bind /usr /usr \
  --ro-bind /bin /bin \
  --ro-bind /lib /lib \
  --ro-bind-try /lib64 /lib64 \
  --tmpfs /tmp \
  --proc /proc \
  --dev /dev \
  /bin/sh -lc 'python3 -c "print(\"python-ok\")" && echo sandbox-ok'
```

Expected output:

```text
python-ok
sandbox-ok
```

If this fails, do not start the application yet. Use the troubleshooting
section to resolve the host policy first.

## 5. Prepare the application

The following example assumes the project is deployed at `/srv/deep-agent`
and runs as the `deepagent` user. Replace these values with the real deployment
path and service account.

```bash
cd /srv/deep-agent

python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

python manage.py migrate
python manage.py check
```

The default agent workspace is `<project>/tmp`. Make it private and writable
by only the Django service account:

```bash
sudo install -d \
  -o deepagent \
  -g deepagent \
  -m 0700 \
  /srv/deep-agent/tmp
```

The application virtual environment and the agent workspaces are different:

- `/srv/deep-agent/.venv` contains the Django application's dependencies.
- `/srv/deep-agent/tmp/<workspace UUID>/<conversation>/.venv` is created only
  when an agent needs to install Python packages for that conversation.

## 6. Check systemd restrictions

Bubblewrap needs to create user and network namespaces. If Django runs under
systemd, make sure the unit does not block them.

Avoid settings such as:

```ini
RestrictNamespaces=true
PrivateUsers=true
```

Also review custom `SystemCallFilter` rules. They must not block the namespace,
mount, or network setup operations required by Bubblewrap and slirp4netns.
`NoNewPrivileges=true` is compatible with this guide because Bubblewrap is
non-setuid.

After changing the unit or application code, reload and restart it:

```bash
sudo systemctl daemon-reload
sudo systemctl restart <your-service-name>
sudo systemctl status <your-service-name> --no-pager
```

## 7. Run the project sandbox tests

The normal backend tests verify filesystem and process isolation:

```bash
python manage.py test deep_agent_app.test.test_backend --verbosity 2
```

The opt-in network test creates a temporary conversation `.venv`, downloads a
small package with `pip`, imports it, and deletes the temporary workspace:

```bash
DEEP_AGENT_RUN_NETWORK_TESTS=1 \
python manage.py test deep_agent_app.test.test_backend --verbosity 2
```

Then run the complete project checks:

```bash
ruff check .
python manage.py check
python manage.py test
```

## Troubleshooting

### `Failed RTM_NEWADDR` or `Failed to create NETLINK_ROUTE socket`

Bubblewrap could not finish its isolated network namespace.

```bash
sudo journalctl -k --since '10 minutes ago' --no-pager \
  | grep -E 'apparmor|bwrap|userns|net_admin|setpcap'

sudo aa-status | grep deep-agent-bwrap
stat -c '%U:%G %a %n' /usr/bin/bwrap
```

Confirm that the AppArmor profile is loaded and Bubblewrap reports mode `755`,
not `4755`.

### `slirp4netns is required for isolated agent network access`

Install the package and restart the Django service:

```bash
sudo apt-get install -y slirp4netns
sudo systemctl restart <your-service-name>
```

### `Sandbox network unavailable`

Check that `slirp4netns` can run as the Django service user and that the
systemd unit does not block namespaces or `setns`:

```bash
sudo -u deepagent slirp4netns --version
sudo systemctl cat <your-service-name>
sudo journalctl -u <your-service-name> -n 200 --no-pager
```

### `pip` reports an externally managed Python environment

The agent should create its conversation-local virtual environment first:

```bash
python3 -m venv .venv
pip install <package>
```

The sandbox puts `/workspace/.venv/bin` first on `PATH`, so later `python` and
`pip` commands automatically use that environment.

### It works in a terminal but fails under systemd

Run the smoke test as the service user and inspect the unit's namespace and
system-call restrictions. Also confirm that the service user owns the project
`tmp` directory.

## Security notes

- The agent has general outbound internet access through slirp4netns. Host
  loopback is blocked, but production environments that require egress
  allowlisting should enforce it with an external firewall or proxy.
- A package installed by `pip` can execute package build or installation code.
  Use trusted, pinned packages where possible.
- Never mount the Docker socket, SSH keys, the service user's home directory,
  or application secrets inside the sandbox.
- Keep `/skills` and `/conversations` read-only and the current conversation's
  `/workspace` as the only persistent writable mount.
- Do not solve namespace failures by running Django as root, using a setuid
  Bubblewrap binary, disabling AppArmor globally, or sharing the host network.

## References

- [Ubuntu AppArmor user-namespace restrictions](https://documentation.ubuntu.com/security/security-features/privilege-restriction/apparmor/)
- [Bubblewrap documentation](https://github.com/containers/bubblewrap)
- [slirp4netns documentation](https://github.com/rootless-containers/slirp4netns)


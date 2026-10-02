# Putting GandyTrade Lab on gandytrade.co.uk

Every step runs on your cPanel server as **root** (SSH or WHM → Terminal).
Nothing here changes other accounts: the app runs inside the `gandytradeco`
account, and the only shared step is an Apache reload, the same one cPanel does
whenever a site is added. Apache's settings are tested before that reload and
rolled back automatically if the test fails.

Don't paste passwords, tokens or keys into chat. They only ever go into files on the server.

---

## Step 1: give the server read-only access to the code

Create a key the server uses to download the code from GitHub:

```bash
H=$(getent passwd gandytradeco | cut -d: -f6)
runuser -u gandytradeco -- mkdir -p "$H/.ssh"
runuser -u gandytradeco -- ssh-keygen -t ed25519 -N "" -C "gandytrade-server" -f "$H/.ssh/gandytrade_deploy"
printf 'Host github.com\n  IdentityFile ~/.ssh/gandytrade_deploy\n  IdentitiesOnly yes\n' | runuser -u gandytradeco -- tee -a "$H/.ssh/config" >/dev/null
runuser -u gandytradeco -- chmod 600 "$H/.ssh/config"
cat "$H/.ssh/gandytrade_deploy.pub"
```

Copy the line that starts `ssh-ed25519`, then on GitHub open
**gandytrade-lab → Settings → Deploy keys → Add deploy key**. Paste it, name it
`gandytrade-server`, and leave **Allow write access unticked**. Then download the code:

```bash
runuser -u gandytradeco -- git clone git@github.com:EvolutionMediaMarketing/gandytrade-lab.git "$H/gandytrade-lab"
```

Type `yes` if asked whether to trust github.com.

## Step 2: pre-flight checks (read-only)

```bash
bash /home/gandytradeco/gandytrade-lab/deploy/scripts/01-preflight.sh
```

Everything should say **OK** or **CHECK**. Any **STOP** line means pause and paste the output to Claude.
If the disk quota line says less than about 3 GB, raise it in **WHM → Modify an Account → gandytradeco**.

## Step 3: let the gandytradeco user run its own background services

```bash
bash /home/gandytradeco/gandytrade-lab/deploy/scripts/02-prepare-user.sh
```

## Step 4: build and start the app (a few minutes the first time)

```bash
cd /home/gandytradeco/gandytrade-lab
bash deploy/scripts/as-app-user.sh deploy/scripts/03-install-app.sh
```

At this point the app runs on the server only; it isn't reachable from the internet yet.

## Step 5: create your login

```bash
bash deploy/scripts/as-app-user.sh podman exec -it gandytrade-app python -m app.cli create-user
```

Choose a username and a password of 12+ characters. It then shows a QR code:
scan it with your authenticator app (it appears as **GandyTrade Lab**).

## Step 6: put it on gandytrade.co.uk behind the password gate

```bash
bash deploy/scripts/04-apache.sh
```

It asks you to choose a **separate** username and password for the gate: the first
prompt anyone sees on the site. Then open https://gandytrade.co.uk:

1. The browser asks for the gate username and password.
2. The app's sign-in page asks for your app username, password and 6-digit code.

Until you add data keys, charts show **sample data**, clearly labelled.

---

## Adding the free data keys later

```bash
H=/home/gandytradeco
nano $H/gandytrade/app.env      # fill in GT_OANDA_TOKEN= and GT_TWELVEDATA_KEY=
cd $H/gandytrade-lab
bash deploy/scripts/as-app-user.sh systemctl --user restart gandytrade-app
```

Use a token from an OANDA **demo (fxTrade Practice)** account only.

For London shares, get a free key at alphavantage.co (Get free API key) and add a line
`GT_ALPHAVANTAGE_KEY=` with it to the same file, then restart as above. The free plan allows
25 requests a day, so each UK share refreshes at most twice a day; daily, weekly and monthly charts only.

## Updating to a new version

```bash
cd /home/gandytradeco/gandytrade-lab
bash deploy/scripts/as-app-user.sh deploy/scripts/update.sh
```

## Useful commands

| What | Command (from `/home/gandytradeco/gandytrade-lab`) |
| --- | --- |
| Is it running? | `bash deploy/scripts/as-app-user.sh systemctl --user status gandytrade-app` |
| Recent app logs | `bash deploy/scripts/as-app-user.sh podman logs --tail 50 gandytrade-app` |
| Locked out after failed sign-ins | `bash deploy/scripts/as-app-user.sh podman exec -it gandytrade-app python -m app.cli unlock` |
| New phone / reset two-factor | `bash deploy/scripts/as-app-user.sh podman exec -it gandytrade-app python -m app.cli reset-2fa` |
| Change app password | `bash deploy/scripts/as-app-user.sh podman exec -it gandytrade-app python -m app.cli set-password` |
| Change gate password | `htpasswd -B /etc/gandytrade/htpasswd <gate-username>` |
| Sign out every browser now (lost laptop or phone) | `bash deploy/scripts/as-app-user.sh podman exec -it gandytrade-app python -m app.cli sign-out-everywhere` |
| Is the paper trading worker running? | `bash deploy/scripts/as-app-user.sh systemctl --user status gandytrade-worker` |
| Worker logs (stops and targets it closed) | `bash deploy/scripts/as-app-user.sh podman logs --tail 50 gandytrade-worker` |
| Who signed in, failed attempts, changes | `bash deploy/scripts/as-app-user.sh podman exec -it gandytrade-app python -m app.cli audit` |

## Security settings in place

- **Password gate, then app sign-in with two-factor.** Two separate passwords.
- **Only Apache can talk to the app.** Apache adds a secret to every request (kept in `/etc/gandytrade/proxy-secret.conf`, readable by root only). Anything else on the server that connects to port 8601 directly gets "Forbidden". Re-running `04-apache.sh` keeps the same secret; delete that file first to make a new one.
- **Sessions end on their own:** after 30 minutes without you using the page, or 12 hours in total. Changing your password or two-factor signs out every browser.
- **HTTPS remembered** by your browser for a year (HSTS).
- **Locked-down containers:** read-only files, no Linux capabilities, CPU, memory and process caps where the server allows them.
- **Outbound allowlist:** the app can only contact the OANDA practice feed and Twelve Data, over HTTPS.
- **No keys in logs:** keys travel in headers and log lines are scrubbed.
- **Checked packages:** every Python package is verified against a recorded hash; GitHub scans every push for leaked keys.

If the "Only Apache" check ever blocks you by mistake, remove the `GT_PROXY_SECRET=` line from
`/home/gandytradeco/gandytrade/app.env` and restart the app; the password gate still protects the site.

## Undo

Take the site offline (removes only gandytrade.co.uk's added Apache settings):

```bash
bash /home/gandytradeco/gandytrade-lab/deploy/scripts/04-apache.sh --remove
```

Stop the app:

```bash
cd /home/gandytradeco/gandytrade-lab
bash deploy/scripts/as-app-user.sh systemctl --user stop gandytrade-app gandytrade-db
```

## Backups

Nightly backups (test-restored, encrypted, and copied to a Backblaze B2 bucket) are set up and restored as described in [BACKUPS.md](BACKUPS.md).

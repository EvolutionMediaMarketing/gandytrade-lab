# Backups

Every night, at about 02:30 to 03:30 UK time, the server:

1. copies the database to `~/gandytrade/backups` (owner-only; the newest 14 are kept there);
2. **proves the copy works** by loading it into a scratch database and comparing it with the real one;
3. **encrypts** it with your backup passphrase and uploads it to a private Backblaze B2 bucket;
4. records the result. **Settings → Backups** shows the history, and a red banner appears on every
   page if no backup has worked for two days.

The key on the server can only **write** to that one bucket. It can't read, list or delete your
backups, and it can't touch anything else in your Backblaze account. Backblaze only ever stores
scrambled data: without your passphrase nobody, including Backblaze, can read it.

Until steps A to D below are done, steps 1, 2 and 4 still run every night, but the copies stay on
the server.

## A. Create the bucket (Backblaze website, about 10 minutes)

1. Sign up at backblaze.com for **B2 Cloud Storage** (the free tier is plenty: the database is a few
   megabytes). When asked for a **region**, choose **EU Central**.
2. Go to **B2 Cloud Storage → Buckets → Create a Bucket**:
   - **Bucket name:** something unique, e.g. `gandytrade-backups-` followed by a few random letters
   - **Files in bucket are:** **Private**
   - Leave the other options as they are, and create it.
3. On the new bucket's card, note the **Endpoint**. It looks like `s3.eu-central-003.backblazeb2.com`.
4. On the same card, open **Lifecycle Settings** and choose **Use custom lifecycle rules**:
   - **File name prefix:** `nightly/`
   - **Days from uploading to hiding:** `30`
   - **Days from hiding to deleting:** `7`

   This keeps about 30 days of nightly backups, and Backblaze deletes older ones itself, so the
   server never needs permission to delete.
5. Go to **B2 Cloud Storage → Application Keys → Add a New Application Key**:
   - **Name of key:** `gandytrade-server`
   - **Allow access to Bucket(s):** your new bucket only (not "All")
   - **Type of Access:** **Write Only**
   - Leave the rest blank and create it.
6. Backblaze shows a **keyID** and an **applicationKey**. The applicationKey is shown **once only**.
   Keep the page open for step C, and **don't paste either into a chat, email or screenshot**.

## B. Make the backup passphrase (server Terminal, as root)

```
openssl rand -base64 33
```

This prints a long random passphrase. **Save it in your password manager now** (Proton Pass is
ideal), named something like "GandyTrade backup passphrase". Without it the backups can't be
restored, and it can't be recovered.

## C. Add the settings to the server

```
nano /home/gandytradeco/gandytrade/app.env
```

Add these five lines at the end, filling in your values with no quotes and no spaces:

```
GT_BACKUP_ENDPOINT=s3.eu-central-003.backblazeb2.com
GT_BACKUP_BUCKET=your-bucket-name
GT_BACKUP_KEY_ID=the keyID
GT_BACKUP_KEY=the applicationKey
GT_BACKUP_PASSPHRASE=the passphrase from step B
```

Save with **Ctrl+O, Enter**, then exit with **Ctrl+X**. Then close the Backblaze key page.

## D. Install and test

```
cd /home/gandytradeco/gandytrade-lab && runuser -u gandytradeco -- git pull --ff-only && bash deploy/scripts/as-app-user.sh deploy/scripts/update.sh
```

Check the bucket connection. This uploads a tiny encrypted test file to the bucket's `test/` folder:

```
bash deploy/scripts/as-app-user.sh podman run --rm --env-file /home/gandytradeco/gandytrade/app.env localhost/gandytrade-app:latest python -m app.backup test
```

Then run a full backup now, rather than waiting for tonight:

```
bash deploy/scripts/as-app-user.sh deploy/scripts/backup.sh
```

You should see three **OK** lines: dumped, test restore matched, encrypted and uploaded. In
Backblaze, **Browse Files** should show a `nightly/` folder with the file, and **Settings → Backups**
in the app shows the run.

If the test says **403 AccessDenied**, check the key ID, the key and the bucket name. If those are
right, recreate the key with **Type of Access: Read and Write** (still limited to the one bucket).

## Restoring

You should only need this if the server's database is lost or damaged.

- **A copy still on the server** (the newest 14 nights):
  ```
  ls /home/gandytradeco/gandytrade/backups
  bash deploy/scripts/as-app-user.sh deploy/scripts/restore.sh /home/gandytradeco/gandytrade/backups/nightly-YYYYMMDD-HHMMSS.sql.gz
  ```
- **A copy from Backblaze:** in **Browse Files**, open `nightly/`, download the file you want (it
  ends `.enc`), and upload it with cPanel's **File Manager** (signed in as `gandytradeco`) into
  `gandytrade/backups`. Make sure `GT_BACKUP_PASSPHRASE` in `app.env` is the passphrase from your
  password manager, then:
  ```
  bash deploy/scripts/as-app-user.sh deploy/scripts/restore.sh /home/gandytradeco/gandytrade/backups/FILE.sql.gz.enc
  ```

The restore asks you to type `RESTORE`, saves a copy of the current database first (so a restore
can itself be undone the same way), then reloads the backup and restarts the app and worker.

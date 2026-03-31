# MongoDB Migration Guide

This guide provides steps to migrate your MongoDB data (specifically the `tradebot` database) from your local environment to your VPS. It covers two primary workflows: **Docker-based** and **Native OS-installed**.

---

## Prerequisites
- Physical access or SSH access to both Local and VPS.
- `scp` or `rsync` for file transfer.
- MongoDB Tools (`mongodump`, `mongorestore`) installed on the host (for Native workflow) or inside Docker.

---

## Option A: Docker-to-Docker Workflow
Use this if both your local and VPS environments are running MongoDB inside Docker containers.

### Step 1: Export Data (Local)
Create a dump inside the running mongo container:
```bash
docker compose exec mongo mongodump --db tradebot --out /tmp/tradebot_dump
```

### Step 2: Extract Dump to Local Host
Copy the dump from the container to your local filesystem and compress it:
```bash
# Copy from container
docker cp $(docker compose ps -q mongo):/tmp/tradebot_dump ./tradebot_dump

# Compress
tar -czvf tradebot_dump.tar.gz ./tradebot_dump/tradebot
```

### Step 3: Transfer to VPS
Upload the compressed file to your VPS:
```bash
scp tradebot_dump.tar.gz bot@31.97.236.26:/home/bot/
```

### Step 4: Restore Data (VPS)
Uncompress and restore inside the VPS Docker container:
```bash
# 1. Uncompress the dump
tar -xzvf tradebot_dump.tar.gz

# 2. Copy the dump into the VPS mongo container
docker cp ./tradebot_dump/tradebot tradebot-mongo:/tmp/tradebot_restore

# 3. Restore the data (Add --drop to prune existing destination data)
docker compose exec mongo mongorestore --drop --db tradebot /tmp/tradebot_restore
```

---

## Option B: Native OS Workflow
Use this if MongoDB is installed directly on the operating system (e.g., via `apt` or `brew`) in both environments.

### Step 1: Export Data (Local)
Run `mongodump` directly on your host machine:
```bash
mongodump --db tradebot --out ./tradebot_dump
```

### Step 2: Compress Dump
```bash
tar -czvf tradebot_dump.tar.gz ./tradebot_dump/tradebot
```

### Step 3: Transfer to VPS
```bash
scp tradebot_dump.tar.gz bot@31.97.236.26:/home/bot/
```

### Step 4: Restore Data (VPS)
Ensure the `mongod` service is running, then restore:
```bash
# 1. Uncompress the dump
tar -xzvf tradebot_dump.tar.gz

# 2. Restore directly to the system MongoDB (Add --drop to prune existing destination data)
mongorestore --drop --db tradebot ./tradebot_dump/tradebot
```

---

## Troubleshooting & Tips

### 1. Data Pruning (Overwriting)
By default, `mongorestore` **merges** data (it doesn't delete existing records in the destination).
- To **prune/delete** existing collections before restoring, use the `--drop` flag (as shown in the steps above).
- If you omit `--drop`, MongoDB will attempt to insert only new records, which may cause "duplicate key" errors if IDs already exist.

### 2. Cross-Migration (Native to Docker)
If you are moving from a Native OS installation to Docker:
1. Follow **Option B** Steps 1-3.
2. In VPS, follow **Option A** Step 4 (Copy the folder into the container and run `mongorestore`).

### 2. Authentication
If MongoDB has security enabled, add credentials to all `dump`/`restore` commands:
```bash
--username your_user --password your_pass --authSource admin
```

### 3. Cleanup
After verification, delete the temporary files:
```bash
rm -rf ./tradebot_dump ./mongodb_native_dump *.tar.gz
```

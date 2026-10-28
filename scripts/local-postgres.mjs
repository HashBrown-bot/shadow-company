// Workspace-local PostgreSQL. Never writes system configuration or creates OS users.
import EmbeddedPostgres from "embedded-postgres";
import { access, mkdir } from "node:fs/promises";
import path from "node:path";

const databaseDir = path.resolve(process.env.SIM_PG_DIRECTORY || ".local/postgres");
await mkdir(path.resolve(".local"), { recursive: true, mode: 0o700 });
const pg = new EmbeddedPostgres({
  databaseDir,
  port: 55432,
  user: "sim",
  password: "", // No credential exists in this loopback-only development cluster.
  authMethod: "trust",
  persistent: true,
  createPostgresUser: false,
  initdbFlags: ["--encoding=UTF8", "--locale=C"],
  postgresFlags: ["-h", "127.0.0.1", "-k", "", "-c", "timezone=UTC"],
  onLog: () => {},
  onError: (message) => console.error(String(message)),
});

const initialized = await access(path.join(databaseDir, "PG_VERSION")).then(() => true, () => false);
if (!initialized) await pg.initialise();
await pg.start();
const client = pg.getPgClient();
await client.connect();
if (!(await client.query("SELECT 1 FROM pg_database WHERE datname = 'simulation'")).rowCount) {
  await client.query("CREATE DATABASE simulation");
}
const version = (await client.query("SHOW server_version")).rows[0].server_version;
await client.end();
console.log(JSON.stringify({ database: "simulation", host: "127.0.0.1", port: 55432, version }));

let stopping = false;
async function stop() {
  if (stopping) return;
  stopping = true;
  await pg.stop();
  process.exit(0);
}
process.on("SIGINT", stop);
process.on("SIGTERM", stop);

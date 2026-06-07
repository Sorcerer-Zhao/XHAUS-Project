let Redis = null;
try {
  Redis = require("ioredis");
} catch (err) {
  Redis = null;
}

const host = process.env.REDIS_HOST || "127.0.0.1";
const port = parseInt(process.env.REDIS_PORT || "6379", 10);

class MemoryStore {
  constructor() {
    this.values = new Map();
  }

  cleanup(key) {
    const item = this.values.get(key);
    if (item && item.expiresAt && item.expiresAt <= Date.now()) {
      this.values.delete(key);
      return null;
    }
    return item || null;
  }

  async get(key) {
    const item = this.cleanup(key);
    return item ? item.value : null;
  }

  async set(key, value, mode, ttlSeconds) {
    const expiresAt = mode === "EX" && ttlSeconds ? Date.now() + ttlSeconds * 1000 : null;
    this.values.set(key, { value, expiresAt });
    return "OK";
  }

  async del(key) {
    return this.values.delete(key) ? 1 : 0;
  }
}

class RedisOrMemory {
  constructor() {
    this.memory = new MemoryStore();
    this.ready = false;
    if (!Redis) {
      console.log("redis_fallback_memory ioredis_not_installed");
      return;
    }

    this.client = new Redis({
      host,
      port,
      lazyConnect: true,
      enableOfflineQueue: false,
      maxRetriesPerRequest: 1,
      connectTimeout: 700,
      retryStrategy: () => null,
    });

    this.client.on("ready", () => {
      this.ready = true;
      console.log(`redis_ready_${host}:${port}`);
    });

    this.client.on("end", () => {
      this.ready = false;
    });

    this.client.on("error", (err) => {
      this.ready = false;
      console.log("redis_fallback_memory", err && err.message ? err.message : err);
    });

    this.client.connect().catch(() => {
      this.ready = false;
    });
  }

  async get(key) {
    if (!this.client || !this.ready) {
      return this.memory.get(key);
    }
    try {
      return await this.client.get(key);
    } catch (err) {
      this.ready = false;
      return this.memory.get(key);
    }
  }

  async set(key, value, mode, ttlSeconds) {
    if (!this.client || !this.ready) {
      return this.memory.set(key, value, mode, ttlSeconds);
    }
    try {
      return await this.client.set(key, value, mode, ttlSeconds);
    } catch (err) {
      this.ready = false;
      return this.memory.set(key, value, mode, ttlSeconds);
    }
  }

  async del(key) {
    if (!this.client || !this.ready) {
      return this.memory.del(key);
    }
    try {
      return await this.client.del(key);
    } catch (err) {
      this.ready = false;
      return this.memory.del(key);
    }
  }
}

module.exports = new RedisOrMemory();

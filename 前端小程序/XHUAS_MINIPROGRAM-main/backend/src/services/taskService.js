const crypto = require("crypto");

const TASK_TTL_MS = 60 * 60 * 1000;

class TaskService {
  constructor() {
    this.tasks = new Map();
    this.startCleanup();
  }

  startCleanup() {
    const timer = setInterval(() => this.cleanupExpired(), 30 * 60 * 1000);
    if (typeof timer.unref === "function") {
      timer.unref();
    }
  }

  cleanupExpired() {
    const now = Date.now();
    for (const [taskId, task] of this.tasks.entries()) {
      if (task.updatedAt + TASK_TTL_MS <= now) {
        this.tasks.delete(taskId);
      }
    }
  }

  createTask({ userId, sessionId }) {
    const taskId = `t_${crypto.randomUUID()}`;
    const now = Date.now();
    const task = {
      taskId,
      userId,
      sessionId,
      status: "running",
      seq: 0,
      deltas: [],
      createdAt: now,
      updatedAt: now,
      error: null,
      controller: null,
    };
    this.tasks.set(taskId, task);
    return task;
  }

  attachController(taskId, controller) {
    const task = this.tasks.get(taskId);
    if (task) {
      task.controller = controller;
    }
  }

  appendDelta(taskId, content) {
    const task = this.tasks.get(taskId);
    if (!task || task.status !== "running") {
      return null;
    }
    task.seq += 1;
    task.deltas.push({
      seq: task.seq,
      content,
    });
    task.updatedAt = Date.now();
    return task;
  }

  finishTask(taskId) {
    const task = this.tasks.get(taskId);
    if (!task) {
      return null;
    }
    task.status = "done";
    task.updatedAt = Date.now();
    return task;
  }

  failTask(taskId, errorMessage) {
    const task = this.tasks.get(taskId);
    if (!task) {
      return null;
    }
    task.status = "error";
    task.error = errorMessage || "unknown_error";
    task.updatedAt = Date.now();
    return task;
  }

  cancelTask(taskId) {
    const task = this.tasks.get(taskId);
    if (!task) {
      return null;
    }
    if (task.controller) {
      task.controller.abort();
    }
    task.status = "cancelled";
    task.updatedAt = Date.now();
    return task;
  }

  getTask(taskId) {
    return this.tasks.get(taskId) || null;
  }

  getTaskView(taskId, sinceSeq = 0) {
    const task = this.tasks.get(taskId);
    if (!task) {
      return null;
    }
    const deltas = task.deltas.filter((delta) => delta.seq > sinceSeq);
    return {
      task,
      deltas,
    };
  }
}

module.exports = new TaskService();

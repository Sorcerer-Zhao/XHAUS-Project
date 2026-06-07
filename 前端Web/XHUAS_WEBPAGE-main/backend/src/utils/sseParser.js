class SSEParser {
  constructor() {
    this.buffer = "";
    this.eventData = [];
  }

  feed(chunk) {
    this.buffer += chunk;
    const lines = this.buffer.split(/\r?\n/);
    this.buffer = lines.pop() || "";
    const events = [];

    for (const line of lines) {
      if (!line) {
        if (this.eventData.length) {
          events.push(this.eventData.join("\n"));
          this.eventData = [];
        }
        continue;
      }

      if (line.startsWith("data:")) {
        this.eventData.push(line.slice(5).trimStart());
      }
    }

    return events;
  }

  flush() {
    if (!this.eventData.length) {
      return [];
    }
    const events = [this.eventData.join("\n")];
    this.eventData = [];
    return events;
  }
}

module.exports = {
  SSEParser,
};

/**
 * PAL-E Observer Service
 * Watches Palworld save files and broadcasts events via WebSocket.
 */

const chokidar = require('chokidar');
const WebSocket = require('ws');
const { execFile } = require('child_process');
const path = require('path');
const os = require('os');
const fs = require('fs');
const http = require('http');

// Configuration
const CONFIG = {
  wsPort: 8765,
  savePath: path.join(os.homedir(), 'AppData', 'Local', 'Pal', 'Saved', 'SaveGames'),
  debounceMs: 5000,  // Wait 5s after file change before processing
  snapshotScript: path.join(__dirname, 'snapshot.py'),
  snapshotDir: path.join(__dirname, 'snapshots'),
  maxEventHistory: 50,
  parseTimeoutMs: 180000,  // 3 minutes for deep parse
};

// Ensure snapshot directory exists
if (!fs.existsSync(CONFIG.snapshotDir)) {
  fs.mkdirSync(CONFIG.snapshotDir, { recursive: true });
}

// State
let worldState = {
  worldId: null,
  hostPlayer: null,
  players: [],
  palCount: 0,
  baseCount: 0,
  lastParsed: null,
};
let previousSnapshotPath = null;
let eventHistory = [];
let pendingChanges = new Map();  // filePath -> timeout
let lastProcessedTime = 0;

// Load most recent snapshot if exists
function loadLatestSnapshot() {
  try {
    const files = fs.readdirSync(CONFIG.snapshotDir)
      .filter(f => f.startsWith('snapshot_') && f.endsWith('.json'))
      .sort()
      .reverse();

    if (files.length > 0) {
      previousSnapshotPath = path.join(CONFIG.snapshotDir, files[0]);
      console.log(`[Observer] Loaded previous snapshot: ${files[0]}`);
    }
  } catch (e) {
    console.log('[Observer] No previous snapshots found');
  }
}

// Parse save using snapshot.py --json
async function parseSnapshot(savePath) {
  return new Promise((resolve, reject) => {
    const args = [CONFIG.snapshotScript, savePath, '--json', '--no-save'];
    if (previousSnapshotPath && fs.existsSync(previousSnapshotPath)) {
      args.push('--diff', previousSnapshotPath);
    }

    console.log(`[Observer] Parsing: ${path.basename(savePath)}...`);
    const startTime = Date.now();

    execFile('python', args, { timeout: CONFIG.parseTimeoutMs }, (error, stdout, stderr) => {
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);

      if (error) {
        console.error(`[Observer] Parse error after ${elapsed}s: ${error.message}`);
        reject(error);
        return;
      }

      try {
        const result = JSON.parse(stdout);
        console.log(`[Observer] Parsed in ${elapsed}s: ${result.players?.length || 0} players, ${result.pal_count || 0} pals`);
        resolve(result);
      } catch (e) {
        console.error(`[Observer] JSON parse error: ${e.message}`);
        reject(e);
      }
    });
  });
}

// Save snapshot for future diffs
function saveSnapshot(snapshot) {
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const snapshotPath = path.join(CONFIG.snapshotDir, `snapshot_${timestamp}.json`);

  try {
    fs.writeFileSync(snapshotPath, JSON.stringify(snapshot, null, 2));
    previousSnapshotPath = snapshotPath;

    // Clean up old snapshots (keep last 10)
    const files = fs.readdirSync(CONFIG.snapshotDir)
      .filter(f => f.startsWith('snapshot_') && f.endsWith('.json'))
      .sort()
      .reverse();

    for (const file of files.slice(10)) {
      fs.unlinkSync(path.join(CONFIG.snapshotDir, file));
    }

    return snapshotPath;
  } catch (e) {
    console.error(`[Observer] Failed to save snapshot: ${e.message}`);
    return null;
  }
}

// WebSocket server
const wss = new WebSocket.Server({ port: CONFIG.wsPort });

console.log(`[Observer] WebSocket server: ws://localhost:${CONFIG.wsPort}`);

// Broadcast to all clients
function broadcast(data) {
  const message = JSON.stringify(data);
  let clientCount = 0;

  wss.clients.forEach(client => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(message);
      clientCount++;
    }
  });

  if (clientCount > 0) {
    console.log(`[Observer] Broadcast to ${clientCount} client(s): ${data.type}`);
  }
}

// Add event to history and broadcast
function emitEvent(event) {
  eventHistory.unshift(event);
  if (eventHistory.length > CONFIG.maxEventHistory) {
    eventHistory = eventHistory.slice(0, CONFIG.maxEventHistory);
  }
  broadcast(event);
}

// Handle new WebSocket connections
wss.on('connection', (ws) => {
  console.log('[Observer] Client connected');

  // Send greeting with current state
  ws.send(JSON.stringify({
    type: 'greeting',
    message: 'PAL-E Observer connected',
    timestamp: new Date().toISOString(),
    worldState,
    recentEvents: eventHistory.slice(0, 10),
  }));

  ws.on('close', () => {
    console.log('[Observer] Client disconnected');
  });

  ws.on('error', (err) => {
    console.error('[Observer] WebSocket error:', err.message);
  });
});

// Process a file change
async function processFileChange(filePath) {
  const fileName = path.basename(filePath);
  const now = Date.now();

  // Determine file type and how to handle it
  if (fileName === 'Level.sav') {
    // Deep parse Level.sav
    try {
      const snapshot = await parseSnapshot(filePath);

      // Save snapshot for future diffs
      saveSnapshot(snapshot);

      // Update world state
      worldState = {
        worldId: snapshot.world_id || null,
        hostPlayer: snapshot.host_player || null,
        players: snapshot.players || [],
        palCount: snapshot.pal_count || 0,
        baseCount: snapshot.bases?.length || 0,
        lastParsed: new Date().toISOString(),
      };

      // Emit events from diff
      if (snapshot.events && snapshot.events.length > 0) {
        for (const event of snapshot.events) {
          emitEvent({
            type: 'game_event',
            eventType: event.type,
            category: event.category,
            message: event.message,
            priority: event.priority,
            timestamp: new Date().toISOString(),
            worldState,
          });
        }
      } else {
        // No specific events, emit generic save event
        emitEvent({
          type: 'file_changed',
          file: fileName,
          message: 'World saved',
          timestamp: new Date().toISOString(),
          worldState,
        });
      }

      lastProcessedTime = now;

    } catch (err) {
      console.error(`[Observer] Failed to process Level.sav: ${err.message}`);
      // Still emit a file_changed event even if parsing failed
      emitEvent({
        type: 'file_changed',
        file: fileName,
        message: 'Save detected (parse failed)',
        error: err.message,
        timestamp: new Date().toISOString(),
      });
    }

  } else if (fileName.endsWith('.sav')) {
    // Other .sav files - just broadcast file changed
    const fileType = getFileType(filePath);
    emitEvent({
      type: 'file_changed',
      file: fileName,
      fileType,
      message: `${fileType} updated`,
      timestamp: new Date().toISOString(),
    });
  }
}

// Determine file type from path
function getFileType(filePath) {
  const fileName = path.basename(filePath);
  const dirName = path.dirname(filePath);

  if (fileName === 'Level.sav') return 'world';
  if (fileName === 'LevelMeta.sav') return 'metadata';
  if (fileName === 'LocalData.sav') return 'local';
  if (fileName === 'WorldOption.sav') return 'settings';
  if (fileName === 'GlobalPalStorage.sav') return 'global_storage';
  if (fileName === 'UserOption.sav') return 'user_settings';
  if (dirName.includes('Players')) return 'player';

  return 'unknown';
}

// Debounced file change handler
function handleFileChange(filePath) {
  // Clear any pending timeout for this file
  if (pendingChanges.has(filePath)) {
    clearTimeout(pendingChanges.get(filePath));
  }

  // Set new timeout
  const timeout = setTimeout(() => {
    pendingChanges.delete(filePath);
    processFileChange(filePath);
  }, CONFIG.debounceMs);

  pendingChanges.set(filePath, timeout);
}

// File watcher
console.log(`[Observer] Watching: ${CONFIG.savePath}`);

const watcher = chokidar.watch(CONFIG.savePath, {
  ignored: /(^|[\/\\])\../,  // ignore dotfiles
  persistent: true,
  ignoreInitial: true,
  awaitWriteFinish: {
    stabilityThreshold: 2000,
    pollInterval: 500,
  },
  depth: 10,  // Watch nested directories
});

watcher.on('change', (filePath) => {
  if (filePath.endsWith('.sav')) {
    console.log(`[Observer] File changed: ${path.basename(filePath)}`);
    handleFileChange(filePath);
  }
});

watcher.on('add', (filePath) => {
  if (filePath.endsWith('.sav')) {
    console.log(`[Observer] New file: ${path.basename(filePath)}`);
  }
});

watcher.on('error', (error) => {
  console.error(`[Observer] Watcher error: ${error}`);
});

watcher.on('ready', () => {
  console.log('[Observer] File watcher ready');
  console.log('[Observer] Waiting for save file changes...');
});

// HTTP server for REST API (same port as WebSocket)
const httpServer = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET');
  res.setHeader('Content-Type', 'application/json');

  if (req.method === 'GET' && req.url === '/status') {
    res.writeHead(200);
    res.end(JSON.stringify({
      worldState,
      uptime: process.uptime(),
      eventHistoryCount: eventHistory.length,
      watching: CONFIG.savePath,
    }, null, 2));

  } else if (req.method === 'GET' && req.url === '/history') {
    res.writeHead(200);
    res.end(JSON.stringify({
      events: eventHistory,
    }, null, 2));

  } else if (req.method === 'GET' && req.url === '/health') {
    res.writeHead(200);
    res.end(JSON.stringify({
      status: 'healthy',
      timestamp: new Date().toISOString(),
    }));

  } else {
    res.writeHead(404);
    res.end(JSON.stringify({ error: 'Not found' }));
  }
});

// Start HTTP server on different port (8764)
const HTTP_PORT = 8764;
httpServer.listen(HTTP_PORT, () => {
  console.log(`[Observer] REST API: http://localhost:${HTTP_PORT}`);
  console.log(`[Observer]   GET /status  - Current world state`);
  console.log(`[Observer]   GET /history - Recent events`);
  console.log(`[Observer]   GET /health  - Health check`);
});

// Load previous snapshot on startup
loadLatestSnapshot();

// Graceful shutdown
process.on('SIGINT', () => {
  console.log('\n[Observer] Shutting down...');
  watcher.close();
  wss.close();
  httpServer.close();
  process.exit(0);
});

console.log('[Observer] PAL-E Observer started');

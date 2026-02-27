# Mesh Application Ideas

Twenty unconventional applications for Meshtastic/MeshCore networks.

## Games

### 1. Mesh Tag (Manhunt)

GPS-based tag game. One player is "it" and broadcasts their location every 30 seconds. Other players receive the broadcast and must stay out of range. If "it" receives your node's broadcast, you're tagged. Last survivor wins.

Technical: Use position broadcasts + RSSI. "Tag" threshold at -70dBm or stronger.

### 2. Marco Polo

Blind location-finding game. One player hides and broadcasts "Marco" periodically. Seekers respond with "Polo" and use signal strength readings to triangulate. No GPS allowed. First to physically find the hider wins.

Technical: Disable GPS. Players navigate purely by RSSI/SNR readings displayed on screen.

### 3. Slow Chess

Asynchronous chess over mesh. Broadcast moves in algebraic notation. Games can span days. Multiple games can run simultaneously with game IDs. Anyone on the mesh can spectate.

Technical: 4-byte messages ("e2e4"). Store game state locally. Broadcast format: `GAME01:e2e4`

### 4. Mesh Assassin

Social deduction game. Each player receives a secret "target" node ID. You must get within close range of your target to "eliminate" them. Your target doesn't know who's hunting them. Chain of assassins until one remains.

Technical: Bridge assigns targets via DM. Proximity detection via RSSI threshold.

### 5. Twenty Questions

One node thinks of something and broadcasts "Ready". Others ask yes/no questions (one per minute, rate limited). First to guess correctly becomes the next host. All questions and answers visible to the mesh.

Technical: Question queue managed by bridge. Throttle to prevent flooding.

## Art & Creative

### 6. Exquisite Corpse Radio

Collaborative storytelling. Each node adds one sentence to a story, but can only see the previous sentence. After 20 contributions, the complete story is broadcast. Absurdist fiction emerges from the mesh.

Technical: Bridge tracks story state, sends only previous sentence to next contributor.

### 7. Number Station

Mysterious broadcasts of seemingly random numbers at scheduled intervals. No explanation given. Could be an ARG, could be art, could be an actual covert communication channel. Let people speculate.

Technical: Cron job broadcasts sequences. Optional: actual encrypted messages for those who figure out the key.

### 8. Haiku Chain

Collaborative haiku. First node sends 5 syllables. Second adds 7. Third completes with 5. Bridge validates syllable count (approximately). Completed haiku posted to IRC/archive.

Technical: CMU pronouncing dictionary for syllable counting. Store incomplete chains with timeout.

### 9. Signal Paintings

Visualize mesh topology as art. Each node's position, signal strength, and message frequency becomes a data point. Generate abstract visualizations. The mesh paints itself.

Technical: Collect telemetry, feed to Processing/p5.js, generate and post images to IRC.

### 10. One Character Per Hour

Extreme slow communication. Each node can broadcast exactly one character per hour. Collectively spell out messages across days. Patience as art form.

Technical: Rate limit enforcement. Running buffer displayed on web dashboard. What will the mesh say today?

## Practical (But Weird)

### 11. Dead Man's Switch

Check in daily via mesh. If you miss three consecutive check-ins, the network alerts your emergency contacts. For solo hikers, elderly relatives, or the paranoid.

Technical: Bridge tracks last-seen timestamps. Escalating alerts via IRC/email/SMS gateway.

### 12. Mesh Confessional

Anonymous confession booth. Send a message to the "confessional" node. It strips all identifying information and rebroadcasts to a public IRC channel. Judgment-free zone. Catharsis via radio.

Technical: Bridge strips node ID, randomizes timing to prevent correlation. Content moderation optional.

### 13. Lost Item Network

Attach small mesh nodes to valuable items. If your node detects your lost item's broadcast, it alerts you with approximate direction.�crowd-sourced item finding.

Technical: Passive listening mode. Alert when specific node ID heard. RSSI indicates "warmer/colder".

### 14. Paranoia Ping

For the anxious. Broadcast a "ping" to confirm others are out there. Anyone who hears responds automatically. Comfort in knowing the mesh is alive. Particularly relevant during disasters.

Technical: Auto-responder mode. Configurable quiet hours. "23 nodes heard your ping."

### 15. Weather Betting Pool

Predict tomorrow's weather. Nodes with environmental sensors verify results. Winners get bragging rights (or mesh-tracked points). Distributed, trust-minimized weather gambling.

Technical: Bridge collects predictions, queries sensor nodes at deadline, calculates winners.

## Experimental

### 16. Mesh Tamagotchi

A virtual creature that lives on the mesh. It needs "feeding" (messages from different nodes) to survive. If network activity drops, it gets sad. If the mesh goes silent for too long, it dies. Restart requires consensus from 5 nodes.

Technical: Bridge maintains creature state. Health decreases over time, increases with unique node activity.

### 17. Cooperative Music Box

Send MIDI note numbers. Bridge collects notes from multiple nodes, quantizes to a beat, plays the result. The mesh makes music together. Cacophony or symphony depends on coordination.

Technical: Collect notes over 30-second windows. Quantize to 120bpm grid. Render to audio, post to IRC as clip.

### 18. Mesh Ouija

Collaborative "spirit board". Each node submits a letter or "wait". Plurality wins each round. The mesh collectively spells messages from beyond (or from the collective unconscious of the participants).

Technical: Voting rounds with 60-second timeout. Bridge tallies and broadcasts winning letter.

### 19. Proof of Presence

Location-stamped check-ins. Visit physical locations, broadcast proof. Collect stamps like a digital passport. "I was at the summit." Others can verify if their node also heard you there.

Technical: GPS + timestamp + signature. Bridge maintains location registry. Achievements for rare locations.

### 20. Mesh Telephone

Record a 2-second voice clip. Compress aggressively (Codec2 at 700bps = 175 bytes). Send via mesh. Recipient hears a ghostly, compressed version of your voice. Eerie and functional.

Technical: Codec2 encoding (700-1200bps modes). Split across multiple packets if needed. Reassemble and play on receive.

---

## Implementation Priority Matrix

| Idea | Complexity | Hardware | Novelty |
|------|-----------|----------|---------|
| Slow Chess | Low | None | Medium |
| Marco Polo | Low | None | High |
| Dead Man's Switch | Low | None | Medium |
| Mesh Tag | Medium | GPS | High |
| Exquisite Corpse | Medium | None | High |
| Mesh Confessional | Medium | None | High |
| Number Station | Low | None | High |
| Haiku Chain | Medium | None | Medium |
| Weather Betting | Medium | Sensors | Medium |
| Mesh Tamagotchi | Medium | None | High |
| Signal Paintings | Medium | None | High |
| Cooperative Music | High | Audio out | High |
| Mesh Telephone | High | Codec2 | Very High |
| Proof of Presence | Medium | GPS | Medium |
| Mesh Ouija | Low | None | High |
| Lost Item Network | Medium | Extra nodes | Medium |
| Paranoia Ping | Low | None | Low |
| Twenty Questions | Low | None | Medium |
| One Char Per Hour | Low | None | High |
| Mesh Assassin | Medium | GPS | High |

## Quick Wins (Implement This Weekend)

1. **Slow Chess** - Just message parsing and state tracking
2. **Number Station** - Cron job + message broadcast
3. **Mesh Ouija** - Voting with timeout
4. **Paranoia Ping** - Auto-responder
5. **Dead Man's Switch** - Timestamp tracking + alerts

## Hardware Projects (Need More Nodes)

1. **Lost Item Network** - Cheap nodes on keychains
2. **Weather Betting** - BME280 sensor integration
3. **Mesh Telephone** - Audio codec + speaker/mic
4. **Signal Paintings** - Multiple fixed nodes for coverage mapping

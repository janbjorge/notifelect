# **Notifelect: Robust Leader Election for Distributed Systems Using PostgreSQL NOTIFY**

Notifelect is a Python package designed for seamless leader election in distributed systems. It utilizes the NOTIFY feature of PostgreSQL to manage elections, offering a robust and reliable solution for systems requiring fault tolerance and consistency across nodes. Leveraging the Bully algorithm, Notifelect ensures dynamic leader selection with minimal configuration.

**Why Notifelect?**
- **Efficient Leader Elections**: Utilizes PostgreSQL's NOTIFY and sequences for efficient and accurate leader determination.
- **Asynchronous Operations**: Built with asyncio, allowing for non-blocking, event-driven communication.
- **Easy to Integrate**: Simple API that fits naturally into existing Python applications.

## Getting Started
Installation is straightforward using pip:

```bash
pip install notifelect
python -m notifelect install  # Set the necessary database sequence.
```

## Quick Example
Simulate a leader election among N processes:

```python
import asyncio
import contextlib
import random
import sys
from typing import AsyncGenerator

import asyncpg
from notifelect import election_manager

@contextlib.asynccontextmanager
async def connection() -> AsyncGenerator[asyncpg.Connection, None]:
    conn = await asyncpg.connect()
    try:
        yield conn
    finally:
        await conn.close()

async def process() -> None:
    await asyncio.sleep(random.random() * 2)
    async with connection() as conn, election_manager.Coordinator(conn):
        await asyncio.sleep(float('inf'))

async def main() -> None:
    N = int(sys.argv[1])
    processes = [process() for _ in range(N)]
    await asyncio.gather(*processes)

if __name__ == "__main__":
    asyncio.run(main())
```

## Understanding the Bully Algorithm

The Bully Algorithm is employed by Notifelect to ensure the most suitable node takes leadership in the event of failures or when an election is triggered. Here's how it works:

1. **Election Trigger**: Any node can initiate an election, typically when it detects the absence or failure of the current leader.
2. **Candidate Assertion**: The initiating node sends a 'challenge' to all other nodes with higher IDs (or other priority metrics).
3. **Dominance Establishment**: Responding nodes with higher IDs take over the election process, ensuring the node with the highest priority becomes the leader.
4. **Leader Announcement**: The winning node broadcasts its status as the leader to all other nodes. (TODO)

### Benefits of the Bully Algorithm
- **Fault Tolerance**: Automatically recovers from leader failures, maintaining system stability.
- **Fair Leadership**: The highest priority node always leads, optimizing decision-making processes.
- **Decentralized Control**: No single point of failure, enhancing system resilience.

## Configuring Settings

Notifelect allows for fine-tuning of various parameters to adapt the election process to specific system requirements:

- **Namespace**: Limits the scope of the election to prevent interference from unrelated processes.
- **Election Interval and Timeout**: Manage the frequency and responsiveness of the election process, allowing for customization based on network conditions and system scale.

Adjusting these settings can be done during the initialization of the `Coordinator` component, ensuring that each deployment of Notifelect is optimized for its specific environment and use case.

# HostelShare (MK_Hostel)

A command-line app for students in MK_Hostel to lend and borrow everyday items (plat irons, laptops, knives, hammers, buckets and so on) without the usual "who has the iron?" chaos. Single Python file, no external dependencies.

## Features

- **Hostel-only access**: registration needs a hostel access code
- **Post items to lend** with condition, description, your own rules, and an availability window
- **Browse items** with live status: `AVAILABLE`, `TAKEN`, `OVERDUE`, `NOT YET AVAILABLE`, `EXPIRED`
- **Borrow requests** with pick-up and return times; the owner approves or rejects
- **Clash detection**: overlapping bookings are blocked
- **Loan limits by item type** (see table below) and a safety note per item
- **Private chat** between borrower and owner, per item, with unread counts
- **Public comments and 1-5 ratings** on profiles, only between students who have actually borrowed or lent to each other
- **Auto-save** after every action

## Requirements

- Python 3.8+
- Standard library only

## Running

```bash
python MK_hostel_share.py
```

On first run, choose **Register** and enter the hostel access code. The default code is `HOSTEL123`. To change it, set an environment variable before starting:

```bash
# Linux / macOS
HOSTEL_CODE=mysecretcode python MK_hostel_share.py

# Windows (PowerShell)
$env:HOSTEL_CODE="mysecretcode"; python MK_hostel_share.py
```

## Menu overview

| Option | What it does |
|---|---|
| 1. Browse all items | List everything, optionally only available items; open an item to request it, message the owner, or see their comments |
| 2. Borrowed items | See what's in use and when it's free again |
| 3. Post an item | Pick from the catalog (or "Other"), set condition, rules, and availability dates |
| 4. My items & requests received | Approve/reject requests, mark items returned, message borrowers, remove items |
| 5. Items I borrowed | Track your requests, cancel pending ones, message owners |
| 6. Messages | Inbox of private chats |
| 7. Comments & profiles | View profiles, leave public comments and ratings |

## Borrowing flow

1. Borrower opens an item and chooses **Request to borrow**, giving pick-up and return times.
2. Owner sees the request under **My items** and approves or rejects it.
3. They arrange pick-up through the item chat.
4. Owner marks the item **returned**, and it becomes available again.

Request states: `PENDING` -> `APPROVED` -> `RETURNED`, or `REJECTED` / `CANCELLED`.

### Time input formats

| Format | Example |
|---|---|
| Exact | `2026-11-15 18:30` |
| Now | `now` |
| Relative | `+2h` (in 2 hours) |

Availability dates accept `YYYY-MM-DD` or `+N` (N days from today).

## Item types and loan limits

| Class | Items in catalog | Max loan |
|---|---|---|
| `ElectricalItem` | Plat iron | 3 days |
| `Laptop` | Laptop | 2 days |
| `SharpItem` | Knife, Scissors | 2 days |
| `ToolItem` | Hammer | 3 days |
| `HouseholdItem` | Umbrella, Pegs, Hangers, Bucket, Basin, and any "Other" item | 7 days |

## Rules enforced

- You can't borrow your own item
- Pick-up can't be in the past, and return must be after pick-up
- Requested times must fall inside the owner's availability window
- Requested times can't clash with an approved booking
- One pending request per borrower per item
- Only the owner can remove an item, and not while it's booked or borrowed
- You can only comment on someone you've borrowed from or lent to

## Code structure

The project is built to demonstrate core OOP concepts:

| Concept | Where |
|---|---|
| Abstraction | `Account` and `Item` are abstract base classes |
| Inheritance | `Student(Account)`, `ElectricalItem` / `SharpItem` / `ToolItem` / `HouseholdItem` (Item), `Laptop(ElectricalItem)` |
| Polymorphism | Each item class overrides `category()`, `max_loan_days()`, `safety_note()` |
| Encapsulation | Private password hash in `Account`, private status in `BorrowRequest`, private request list in `Item` |
| Composition | `Item` has an `ItemSpecification` and its `BorrowRequest`s; `HostelPlatform` has students, items, messages, comments |

Main classes: `Account`/`Student`, `BorrowRequest`, `ItemSpecification`, `Item` and subclasses, `Message`, `Comment`, `HostelPlatform` (all the rules and data), `HostelCLI` (menus only, no business logic).

## Data storage

All data is saved to `hostel_data.pkl` in the same folder as the script, using Python's `pickle`. Delete this file to reset everything.

## Known limitations

- Passwords are hashed with plain SHA-256 (no salt), fine for a class project, not for production
- `pickle` files should only be loaded from a source you trust
- Single-user at a time: the data file isn't safe for several people running the app at once
- The default access code is visible in the source, so set `HOSTEL_CODE` for real use

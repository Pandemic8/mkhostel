#!/usr/bin/env python3
"""
HostelShare (For MK_Hostel) - borrow & lend items inside MK_Hostel, from the command line.

Hostel access code: HOSTEL123

"""
import getpass
import hashlib
import os
import pickle
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta

HOSTEL_CODE = os.environ.get("HOSTEL_CODE", "HOSTEL123")
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hostel_data.pkl")
TIME_FMT = "%Y-%m-%d %H:%M"


class HostelError(Exception):
    """Raised for any mistake a user can make (wrong password, clash in times...)."""


def now():
    return datetime.now().replace(second=0, microsecond=0)


def show(t):
    return t.strftime("%d %b %Y, %H:%M")


# ==========================================================================
# ACCOUNTS: abstraction + inheritance + encapsulation
# ==========================================================================
class Account(ABC):
    """Abstract class: you cannot create an Account directly, only a subclass."""

    def __init__(self, username, full_name, password):
        self.username = username.strip().lower()
        self.full_name = full_name.strip()
        self.__password = self.__hash(password)      # private: hidden from outside

    @staticmethod
    def __hash(text):
        return hashlib.sha256(text.encode()).hexdigest()

    def check_password(self, password):
        return self.__hash(password) == self.__password

    @abstractmethod
    def role(self):
        pass

    @abstractmethod
    def profile(self):
        pass


class Student(Account):
    def __init__(self, username, full_name, password, room, phone=""):
        super().__init__(username, full_name, password)
        self.room = room.strip()
        self.phone = phone.strip()

    def role(self):
        return "Student"

    def profile(self):
        return f"{self.full_name} (@{self.username}) - Room {self.room}"


# ==========================================================================
# BORROW REQUEST: encapsulation (status can only change through methods)
# ==========================================================================
class BorrowRequest:
    PENDING, APPROVED, REJECTED, RETURNED, CANCELLED = (
        "PENDING", "APPROVED", "REJECTED", "RETURNED", "CANCELLED")

    def __init__(self, request_id, borrower, start, due):
        self.request_id = request_id
        self.borrower = borrower
        self.start = start                # when the borrower takes the item
        self.due = due                    # when it must be returned
        self.returned_at = None           # when it was really returned
        self.__status = self.PENDING      # private

    @property
    def status(self):                     # read-only from outside
        return self.__status

    def is_active(self):
        return self.__status == self.APPROVED

    def overlaps(self, start, due):
        return self.start < due and start < self.due

    def __change(self, needed, new):
        if self.__status != needed:
            raise HostelError(f"This request is {self.__status}; it must be {needed} for that.")
        self.__status = new

    def approve(self):
        self.__change(self.PENDING, self.APPROVED)

    def reject(self):
        self.__change(self.PENDING, self.REJECTED)

    def cancel(self):
        self.__change(self.PENDING, self.CANCELLED)

    def give_back(self, when):
        self.__change(self.APPROVED, self.RETURNED)
        self.returned_at = when


# ==========================================================================
# ITEMS: abstraction + inheritance + polymorphism + composition
# ==========================================================================
class ItemSpecification:
    """Extra details about an item. An Item HAS one of these (composition)."""

    def __init__(self, condition="Good", description="", rules=""):
        self.condition = condition
        self.description = description
        self.rules = rules


class Item(ABC):
    """Abstract class: each kind of item must say its own category, loan limit and safety note."""

    def __init__(self, item_id, name, owner, spec, available_from, available_until):
        if available_until < available_from:
            raise HostelError("'Available until' cannot be before 'available from'.")
        self.item_id = item_id
        self.name = name.strip()
        self.owner = owner
        self.spec = spec                       # composition: Item HAS a specification
        self.available_from = available_from
        self.available_until = available_until
        self.__requests = []                   # composition + private: Item HAS requests

    # ---- polymorphic methods (subclasses change these) ----
    @abstractmethod
    def category(self):
        pass

    @abstractmethod
    def max_loan_days(self):
        pass

    @abstractmethod
    def safety_note(self):
        pass

    def describe(self):
        return f"{self.name} [{self.category()}] - condition: {self.spec.condition}"

    # ---- requests (private list, controlled access) ----
    @property
    def requests(self):
        return list(self.__requests)

    def find_request(self, request_id):
        for r in self.__requests:
            if r.request_id == request_id:
                return r
        raise HostelError("Request not found.")

    def request_borrow(self, borrower, start, due, at):
        if borrower == self.owner:
            raise HostelError("You cannot borrow your own item.")
        if start < at - timedelta(minutes=5):
            raise HostelError("Pick-up time cannot be in the past.")
        if due <= start:
            raise HostelError("Return time must be after the pick-up time.")
        if start < self.available_from or due > self.available_until:
            raise HostelError(f"Times must be inside the owner's window "
                              f"({show(self.available_from)} to {show(self.available_until)}).")
        if due - start > timedelta(days=self.max_loan_days()):
            raise HostelError(f"{self.category()} items can be borrowed for at most "
                              f"{self.max_loan_days()} day(s).")
        for r in self.__requests:
            if r.is_active() and r.overlaps(start, due):
                raise HostelError("Those times clash with an existing booking.")
            if r.status == BorrowRequest.PENDING and r.borrower == borrower:
                raise HostelError("You already have a pending request for this item.")
        request = BorrowRequest(len(self.__requests) + 1, borrower, start, due)
        self.__requests.append(request)
        return request

    def approve(self, request_id):
        request = self.find_request(request_id)
        for r in self.__requests:
            if r.is_active() and r.overlaps(request.start, request.due):
                raise HostelError("Those times now clash with another approved booking.")
        request.approve()
        return request

    # ---- state at a given moment ----
    def current_loan(self, at):
        for r in self.__requests:
            if r.is_active() and r.start <= at:
                return r
        return None

    def upcoming(self, at):
        return sorted((r for r in self.__requests if r.is_active() and r.start > at),
                      key=lambda r: r.start)

    def free_from(self, at):
        """When the item is free again (after the loan and any bookings straight after it)."""
        loan = self.current_loan(at)
        t = loan.due if loan else at
        for r in self.upcoming(at):
            if r.start <= t:
                t = max(t, r.due)
        return t

    def status(self, at):
        loan = self.current_loan(at)
        if loan:
            return "OVERDUE" if at > loan.due else "TAKEN"
        if at < self.available_from:
            return "NOT YET AVAILABLE"
        if at > self.available_until:
            return "EXPIRED"
        return "AVAILABLE"

    def status_text(self, at):
        status = self.status(at)
        loan = self.current_loan(at)
        if status == "OVERDUE":
            return f"OVERDUE - was due back {show(loan.due)}"
        if status == "TAKEN":
            free = self.free_from(at)
            if free > self.available_until:
                return "TAKEN - the owner's window ends before it comes back"
            return f"TAKEN - available again {show(free)}"
        if status == "AVAILABLE":
            later = self.upcoming(at)
            note = f" (next booked {show(later[0].start)})" if later else ""
            return f"AVAILABLE until {show(self.available_until)}{note}"
        if status == "NOT YET AVAILABLE":
            return f"NOT YET AVAILABLE - opens {show(self.available_from)}"
        return "EXPIRED - owner's window has ended"

    def schedule_lines(self, at):
        lines = []
        loan = self.current_loan(at)
        if loan:
            lines.append(f"Borrowed by @{loan.borrower}: taken {show(loan.start)} -> return by {show(loan.due)}")
        for r in self.upcoming(at):
            lines.append(f"Reserved by @{r.borrower}: from {show(r.start)} -> return by {show(r.due)}")
        return lines


class ElectricalItem(Item):
    def category(self):
        return "Electrical"

    def max_loan_days(self):
        return 3

    def safety_note(self):
        return "Check the cable and switch off after use."


class Laptop(ElectricalItem):                  # inherits from ElectricalItem, which inherits from Item
    def category(self):
        return "Laptop"

    def max_loan_days(self):
        return 2

    def safety_note(self):
        return "Valuable! Borrower is responsible for damage or lost data. Return with the charger."

    def describe(self):
        return super().describe() + " (valuable)"


class SharpItem(Item):
    def category(self):
        return "Sharp"

    def max_loan_days(self):
        return 2

    def safety_note(self):
        return "Sharp - handle carefully, wash it and return with a cover."


class ToolItem(Item):
    def category(self):
        return "Tool"

    def max_loan_days(self):
        return 3

    def safety_note(self):
        return "Return in the same condition."


class HouseholdItem(Item):
    def category(self):
        return "Household"

    def max_loan_days(self):
        return 7

    def safety_note(self):
        return "Return clean and complete (all pegs / hangers)."


CATALOG = {"Plat iron": ElectricalItem, "Laptop": Laptop, "Knife": SharpItem, "Scissors": SharpItem,
           "Hammer": ToolItem, "Umbrella": HouseholdItem, "Pegs": HouseholdItem,
           "Hangers": HouseholdItem, "Bucket": HouseholdItem, "Basin": HouseholdItem}


# ==========================================================================
# MESSAGES AND COMMENTS
# ==========================================================================
class Message:
    """A PRIVATE message between two students about one item."""

    def __init__(self, item_id, sender, recipient, text):
        self.item_id, self.sender, self.recipient, self.text = item_id, sender, recipient, text
        self.sent_at = datetime.now()
        self.read = False


class Comment:
    """A PUBLIC comment written on a student's profile."""

    def __init__(self, author, target, text, as_role, rating=None):
        self.author, self.target, self.text = author, target, text
        self.as_role = as_role                 # "lender" or "borrower"
        self.rating = rating
        self.posted_at = datetime.now()


# ==========================================================================
# THE PLATFORM: composition (it HAS students, items, messages, comments)
# ==========================================================================
class HostelPlatform:
    def __init__(self):
        self.students = {}
        self.items = {}
        self.messages = []
        self.comments = []

    # ---- saving / loading ----
    def save(self):
        with open(DATA_FILE, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load():
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "rb") as f:
                return pickle.load(f)
        return HostelPlatform()

    # ---- students ----
    def register(self, code, username, full_name, password, room, phone=""):
        if code != HOSTEL_CODE:
            raise HostelError("Wrong hostel access code. This platform is for our hostel only.")
        username = username.strip().lower()
        if len(username) < 3 or len(password) < 4 or not room.strip():
            raise HostelError("Username needs 3+ characters, password 4+, and a room number.")
        if username in self.students:
            raise HostelError("That username is taken.")
        student = Student(username, full_name, password, room, phone)
        self.students[username] = student
        return student

    def login(self, username, password):
        student = self.students.get(username.strip().lower())
        if student is None or not student.check_password(password):
            raise HostelError("Wrong username or password.")
        return student

    def get_student(self, username):
        if username not in self.students:
            raise HostelError("No such student.")
        return self.students[username]

    # ---- items ----
    def post_item(self, owner, name, item_class, spec, start, end):
        item_id = max(self.items, default=0) + 1
        item = item_class(item_id, name, owner, spec, start, end)
        self.items[item_id] = item
        return item

    def get_item(self, item_id):
        if item_id not in self.items:
            raise HostelError("No such item.")
        return self.items[item_id]

    def browse(self, at, only_available=False):
        items = sorted(self.items.values(), key=lambda i: (i.name.lower(), i.item_id))
        return [i for i in items if i.status(at) == "AVAILABLE"] if only_available else items

    def borrowed_items(self, at):
        busy = [i for i in self.items.values() if i.current_loan(at) or i.upcoming(at)]
        return sorted(busy, key=lambda i: i.free_from(at))

    def items_of(self, owner):
        return [i for i in self.items.values() if i.owner == owner]

    def requests_by(self, username):
        return [(i, r) for i in self.items.values() for r in i.requests if r.borrower == username]

    def remove_item(self, item_id, username):
        item = self.get_item(item_id)
        if item.owner != username:
            raise HostelError("Only the owner can remove an item.")
        if any(r.is_active() for r in item.requests):
            raise HostelError("Item is booked or borrowed - settle that first.")
        del self.items[item_id]

    # ---- private messages ----
    def send_message(self, item_id, sender, recipient, text):
        item = self.get_item(item_id)
        self.get_student(recipient)
        if not text.strip():
            raise HostelError("Message is empty.")
        if sender == recipient or item.owner not in (sender, recipient):
            raise HostelError("Messages about an item must be between the owner and one other student.")
        self.messages.append(Message(item_id, sender, recipient, text.strip()))

    def thread(self, item_id, a, b):
        return [m for m in self.messages if m.item_id == item_id and {m.sender, m.recipient} == {a, b}]

    def conversations(self, username):
        pairs = []
        for m in sorted(self.messages, key=lambda m: m.sent_at, reverse=True):
            if username in (m.sender, m.recipient):
                other = m.recipient if m.sender == username else m.sender
                if (m.item_id, other) not in pairs:
                    pairs.append((m.item_id, other))
        return pairs

    def unread_count(self, username):
        return sum(1 for m in self.messages if m.recipient == username and not m.read)

    def mark_read(self, item_id, me, other):
        for m in self.thread(item_id, me, other):
            if m.recipient == me:
                m.read = True

    # ---- public comments ----
    def add_comment(self, author, target, text, rating=None):
        self.get_student(target)
        if author == target:
            raise HostelError("You cannot comment on yourself.")
        if not text.strip():
            raise HostelError("Comment is empty.")
        if rating is not None and not 1 <= rating <= 5:
            raise HostelError("Rating must be 1 to 5.")
        lender = None
        for item in self.items.values():
            for r in item.requests:
                if r.status in (BorrowRequest.APPROVED, BorrowRequest.RETURNED) \
                        and {item.owner, r.borrower} == {author, target}:
                    lender = item.owner
        if lender is None:
            raise HostelError("You can only comment on someone you have borrowed from or lent to.")
        role = "lender" if target == lender else "borrower"
        self.comments.append(Comment(author, target, text.strip(), role, rating))
        return role

    def comments_for(self, username):
        return sorted((c for c in self.comments if c.target == username),
                      key=lambda c: c.posted_at, reverse=True)

    def average_rating(self, username):
        ratings = [c.rating for c in self.comments if c.target == username and c.rating]
        return round(sum(ratings) / len(ratings), 1) if ratings else None


# ==========================================================================
# COMMAND-LINE INTERFACE (only talks to the platform; holds no rules)
# ==========================================================================
def ask(prompt, default=""):
    text = input(f"{prompt}" + (f" [{default}]" if default else "") + ": ").strip()
    return text or default


def ask_int(prompt):
    while True:
        try:
            return int(input(f"{prompt}: ").strip())
        except ValueError:
            print("  Please enter a number.")


def ask_date(prompt, default=None):
    while True:
        raw = ask(f"{prompt} (YYYY-MM-DD or +N days from today)", str(default) if default else "")
        try:
            if raw.startswith("+"):
                return date.today() + timedelta(days=int(raw[1:]))
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            print("  Invalid date.")


def ask_time(prompt, default=None):
    print("  Time formats:  2026-11-15 18:30   |   now   |   +2h (in 2 hours)")
    while True:
        raw = input(f"{prompt}" + (f" [Enter = {show(default)}]" if default else "") + ": ").strip().lower()
        if not raw and default:
            return default
        try:
            if raw == "now":
                return now()
            if raw.startswith("+") and raw.endswith("h"):
                return now() + timedelta(hours=int(raw[1:-1]))
            return datetime.strptime(raw, TIME_FMT)
        except ValueError:
            print("  Invalid time. Include hour and minute, e.g. 2026-11-15 18:30")


def title(text):
    print("\n" + "=" * 60 + f"\n {text}\n" + "=" * 60)


class HostelCLI:
    def __init__(self, platform):
        self.platform = platform
        self.user = None

    def run(self):
        title("HostelShare - borrow & lend inside our hostel")
        while True:
            try:
                self.user_menu() if self.user else self.welcome_menu()
            except HostelError as error:
                print(f"\n  ! {error}")
            except (KeyboardInterrupt, EOFError):
                self.platform.save()
                print("\nGoodbye!")
                return
            self.platform.save()

    def welcome_menu(self):
        print("\n1) Log in\n2) Register\n0) Exit")
        choice = ask("Choose")
        if choice == "1":
            name = ask("Username")
            self.user = self.platform.login(name, getpass.getpass("Password: "))
            print(f"\nWelcome back, {self.user.full_name}!")
        elif choice == "2":
            code = ask("Hostel access code")
            username = ask("Choose a username")
            full_name = ask("Full name")
            room = ask("Room number")
            phone = ask("Phone (optional)")
            password = getpass.getpass("Password: ")
            self.user = self.platform.register(code, username, full_name, password, room, phone)
            print("\nAccount created. You are logged in.")
        elif choice == "0":
            raise EOFError

    def user_menu(self):
        at = now()
        me = self.user.username
        pending = sum(1 for i in self.platform.items_of(me)
                      for r in i.requests if r.status == BorrowRequest.PENDING)
        title(f"Menu - {self.user.full_name}   ({show(at)})")
        print(f"1) Browse all items\n"
              f"2) Borrowed items & when they're free again  ({len(self.platform.borrowed_items(at))} in use)\n"
              f"3) Post an item to lend\n"
              f"4) My items & requests received  ({pending} pending)\n"
              f"5) Items I borrowed\n"
              f"6) Messages  ({self.platform.unread_count(me)} unread)\n"
              f"7) Comments & profiles\n"
              f"0) Log out")
        actions = {"1": self.browse, "2": self.borrowed_items, "3": self.post_item,
                   "4": self.my_items, "5": self.my_borrowings, "6": self.inbox, "7": self.profiles}
        choice = ask("Choose")
        if choice == "0":
            self.user = None
        elif choice in actions:
            actions[choice]()

    # ---- browsing ----
    def print_items(self, items):
        at = now()
        print(f"\n{'ID':<4}{'Item':<14}{'Owner':<12}Status\n" + "-" * 78)
        for i in items:
            print(f"{i.item_id:<4}{i.name[:13]:<14}{i.owner[:11]:<12}{i.status_text(at)}")
            for line in i.schedule_lines(at):
                print(f"      > {line}")

    def browse(self):
        only = ask("Show only available items? (y/n)", "n").lower() == "y"
        items = self.platform.browse(now(), only)
        if not items:
            print("\nNo items to show yet.")
            return
        title("Items in the hostel")
        self.print_items(items)
        raw = ask("\nEnter an item ID to open it (Enter to go back)")
        if raw.isdigit():
            self.item_page(self.platform.get_item(int(raw)))

    def borrowed_items(self):
        at = now()
        items = self.platform.borrowed_items(at)
        title("Items already borrowed or reserved")
        if not items:
            print("\nNothing is borrowed right now - every listed item is free to request.")
            return
        for i in items:
            print(f"\n#{i.item_id} {i.name}  (owner @{i.owner})")
            print(f"   Status: {i.status_text(at)}")
            for line in i.schedule_lines(at):
                print(f"   {line}")
            if i.current_loan(at) and i.free_from(at) <= i.available_until:
                print(f"   Can be borrowed again from: {show(i.free_from(at))}")
        raw = ask("\nEnter an item ID to open it (Enter to go back)")
        if raw.isdigit():
            self.item_page(self.platform.get_item(int(raw)))

    def item_page(self, item):
        while True:
            at = now()
            title(f"{item.name}  (#{item.item_id})")
            print(f"Type        : {item.describe()}")
            print(f"Owner       : {self.platform.get_student(item.owner).profile()}")
            print(f"Status      : {item.status_text(at)}")
            print(f"Offered     : {show(item.available_from)} to {show(item.available_until)}"
                  f"  (max {item.max_loan_days()} day(s) per loan)")
            loan = item.current_loan(at)
            if loan:
                print(f"Borrowed by : @{loan.borrower}\nBorrowed at : {show(loan.start)}"
                      f"\nReturn time : {show(loan.due)}")
            for r in item.upcoming(at):
                print(f"Reserved    : @{r.borrower}, {show(r.start)} -> {show(r.due)}")
            if item.spec.description:
                print(f"Details     : {item.spec.description}")
            if item.spec.rules:
                print(f"Owner rules : {item.spec.rules}")
            print(f"Safety      : {item.safety_note()}")
            rating = self.platform.average_rating(item.owner)
            print(f"Lender score: {rating if rating else 'no ratings yet'}")
            print("\n1) Request to borrow\n2) Message the owner\n3) See owner's comments\n0) Back")
            choice = ask("Choose")
            if choice == "1":
                self.request_item(item)
            elif choice == "2":
                self.chat(item, item.owner)
            elif choice == "3":
                self.show_profile(item.owner)
            elif choice == "0":
                return

    def request_item(self, item):
        at = now()
        print(f"\nOffered {show(item.available_from)} to {show(item.available_until)}; "
              f"max {item.max_loan_days()} day(s) per loan.")
        for line in item.schedule_lines(at):
            print(f"  Already booked -> {line}")
        start = ask_time("Pick-up time", max(at, item.available_from))
        due = ask_time("Return time")
        request = item.request_borrow(self.user.username, start, due, at)
        print(f"\nRequest #{request.request_id} sent to @{item.owner}.")
        print(f"  You take it : {show(start)}\n  You return  : {show(due)}")
        print("  Track it under 'Items I borrowed' and message the owner to arrange pick-up.")

    # ---- posting and managing ----
    def post_item(self):
        title("Post an item")
        names = list(CATALOG)
        for n, name in enumerate(names, 1):
            print(f"{n:>2}) {name}")
        print(f"{len(names) + 1:>2}) Other")
        pick = ask_int("Choose")
        if 1 <= pick <= len(names):
            name, item_class = names[pick - 1], CATALOG[names[pick - 1]]
        else:
            name, item_class = ask("Item name"), HouseholdItem
        spec = ItemSpecification(ask("Condition (New/Good/Fair/Old)", "Good"),
                                 ask("Short description (optional)"),
                                 ask("Your rules for borrowers (optional)"))
        start = ask_date("Available from", date.today())
        end = ask_date("Available until")
        item = self.platform.post_item(
            self.user.username, name, item_class, spec,
            datetime.combine(start, datetime.min.time()),
            datetime.combine(end, datetime.min.time()).replace(hour=23, minute=59))
        print(f"\nPosted! '{item.name}' is #{item.item_id}. Max loan: {item.max_loan_days()} day(s).")

    def my_items(self):
        items = self.platform.items_of(self.user.username)
        if not items:
            print("\nYou have not posted any items.")
            return
        title("My items")
        self.print_items(items)
        raw = ask("\nEnter an item ID to manage it (Enter to go back)")
        if raw.isdigit():
            item = self.platform.get_item(int(raw))
            if item.owner != self.user.username:
                raise HostelError("That is not your item.")
            self.manage_item(item)

    def manage_item(self, item):
        while True:
            title(f"Managing {item.name} (#{item.item_id})")
            print(f"Status: {item.status_text(now())}")
            for r in item.requests:
                back = f"  returned {show(r.returned_at)}" if r.returned_at else ""
                print(f"  Request #{r.request_id}: @{r.borrower}  {show(r.start)} -> {show(r.due)}"
                      f"  [{r.status}]{back}")
            print("\n1) Approve a request\n2) Reject a request\n3) Mark item as returned"
                  "\n4) Message a borrower\n5) Remove item\n0) Back")
            choice = ask("Choose")
            if choice == "1":
                r = item.approve(ask_int("Request number"))
                print(f"Approved. @{r.borrower} takes it {show(r.start)} and returns it {show(r.due)}.")
            elif choice == "2":
                item.find_request(ask_int("Request number")).reject()
                print("Rejected.")
            elif choice == "3":
                r = item.find_request(ask_int("Request number"))
                r.give_back(now())
                print(f"Marked returned at {show(r.returned_at)} - the item is available again.")
            elif choice == "4":
                self.chat(item, ask("Borrower username").lower())
            elif choice == "5":
                self.platform.remove_item(item.item_id, self.user.username)
                print("Item removed.")
                return
            elif choice == "0":
                return

    # ---- borrower side ----
    def my_borrowings(self):
        rows = self.platform.requests_by(self.user.username)
        if not rows:
            print("\nYou have not requested anything yet.")
            return
        title("Items I requested / borrowed")
        for item, r in rows:
            print(f"\n#{item.item_id} {item.name}  (owner @{item.owner})  [{r.status}]  request #{r.request_id}")
            print(f"   Take it   : {show(r.start)}\n   Return by : {show(r.due)}")
            if r.returned_at:
                print(f"   Returned  : {show(r.returned_at)}")
        print("\n1) Cancel a pending request\n2) Message an owner\n0) Back")
        choice = ask("Choose")
        if choice == "1":
            item = self.platform.get_item(ask_int("Item ID"))
            request = item.find_request(ask_int("Request number"))
            if request.borrower != self.user.username:
                raise HostelError("That is not your request.")
            request.cancel()
            print("Cancelled.")
        elif choice == "2":
            item = self.platform.get_item(ask_int("Item ID"))
            self.chat(item, item.owner)

    # ---- private chat ----
    def chat(self, item, other):
        self.platform.get_student(other)
        me = self.user.username
        title(f"Private chat with @{other} about {item.name} (#{item.item_id})")
        while True:
            for m in self.platform.thread(item.item_id, me, other):
                who = "You" if m.sender == me else f"@{m.sender}"
                print(f"[{m.sent_at:%d %b %H:%M}] {who}: {m.text}")
            self.platform.mark_read(item.item_id, me, other)
            text = ask("\nType a message (Enter to leave chat)")
            if not text:
                return
            self.platform.send_message(item.item_id, me, other, text)

    def inbox(self):
        me = self.user.username
        chats = self.platform.conversations(me)
        if not chats:
            print("\nNo messages yet. Open an item and choose 'Message the owner'.")
            return
        title("Messages")
        for n, (item_id, other) in enumerate(chats, 1):
            new = sum(1 for m in self.platform.thread(item_id, me, other)
                      if m.recipient == me and not m.read)
            print(f"{n}) @{other} about {self.platform.get_item(item_id).name} (#{item_id})"
                  + (f"  ** {new} new" if new else ""))
        pick = ask("Open conversation number (Enter to go back)")
        if pick.isdigit() and 1 <= int(pick) <= len(chats):
            item_id, other = chats[int(pick) - 1]
            self.chat(self.platform.get_item(item_id), other)

    # ---- public comments ----
    def profiles(self):
        title("Comments & profiles")
        print("1) View a student's profile and comments\n2) Write a public comment\n"
              "3) See comments about me\n0) Back")
        choice = ask("Choose")
        if choice == "1":
            self.show_profile(ask("Username").lower())
        elif choice == "2":
            target = ask("Who do you want to comment on (username)").lower()
            text = ask("Your comment")
            raw = ask("Rating 1-5 (optional)")
            role = self.platform.add_comment(self.user.username, target, text,
                                             int(raw) if raw.isdigit() else None)
            print(f"\nPosted publicly on @{target}'s profile (as {role}).")
        elif choice == "3":
            self.show_profile(self.user.username)

    def show_profile(self, username):
        student = self.platform.get_student(username)
        rating = self.platform.average_rating(username)
        title(f"Profile: {student.full_name} (@{username})")
        print(f"Room {student.room}   |   Average rating: {rating if rating else 'none yet'}")
        comments = self.platform.comments_for(username)
        if not comments:
            print("\nNo comments yet.")
        for c in comments:
            stars = f" {'*' * c.rating}" if c.rating else ""
            print(f"\n[{c.posted_at:%d %b %Y}] @{c.author} as {c.as_role}:{stars}\n   \"{c.text}\"")
        input("\nPress Enter to continue...")


if __name__ == "__main__":
    HostelCLI(HostelPlatform.load()).run()

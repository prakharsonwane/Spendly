import os
import io
import csv
import re
import calendar
from datetime import date, datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session, Response
)
from sqlalchemy import or_
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, User, Account, Transaction, Budget


# -------------------- APP CONFIGURATION --------------------

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "SPENDLY_SECRET_KEY",
    "local-only-change-this-secret-before-deployment"
)

database_url = os.environ.get("DATABASE_URL")

if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace(
        "postgres://", "postgresql://", 1
    )

app.config["SQLALCHEMY_DATABASE_URI"] = (
    database_url
    or "sqlite:///" + os.path.join(BASE_DIR, "spendly_v2.db")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


# -------------------- CATEGORIES --------------------

EXPENSE_CATEGORIES = [
    "Food",
    "Entertainment",
    "Travel",
    "Shopping",
    "Bills",
    "Education",
    "Health",
    "Other"
]

INCOME_CATEGORIES = [
    "Pocket Money",
    "Salary",
    "Gift",
    "Other Income"
]

CATEGORIES = EXPENSE_CATEGORIES.copy()

ALL_CATEGORIES = list(dict.fromkeys(
    EXPENSE_CATEGORIES + INCOME_CATEGORIES
))

OVERALL_BUDGET_CATEGORY = "Overall"


# -------------------- HELPER FUNCTIONS --------------------

def valid_month(value):
    try:
        return (
            isinstance(value, str)
            and len(value) == 7
            and datetime.strptime(value, "%Y-%m").strftime("%Y-%m")
            == value
        )
    except (ValueError, TypeError):
        return False


def valid_date(value):
    try:
        return (
            isinstance(value, str)
            and date.fromisoformat(value).isoformat() == value
        )
    except (ValueError, TypeError):
        return False


def parse_amount(value):
    try:
        amount = round(float(value), 2)

        if 0 < amount <= 100000000:
            return amount

    except (ValueError, TypeError):
        pass

    return None


def next_month(month):
    year, number = map(int, month.split("-"))

    if number == 12:
        return f"{year + 1}-01-01"

    return f"{year}-{number + 1:02d}-01"


def selected_month():
    month = request.args.get(
        "month",
        date.today().strftime("%Y-%m")
    )

    return (
        month
        if valid_month(month)
        else date.today().strftime("%Y-%m")
    )


def account_field(account_type):
    """Support current and legacy account names."""

    if account_type in ("savings", "main_savings"):
        return "main_savings"

    if account_type in ("pocket", "pocket_balance"):
        return "pocket_balance"

    return None


def get_account(user_id):
    account = Account.query.filter_by(
        user_id=user_id
    ).first()

    if account is None:
        account = Account(
            user_id=user_id,
            main_savings=0,
            pocket_balance=0
        )

        db.session.add(account)
        db.session.commit()

    return account


def get_month_transactions(user_id, month):
    start_date = month + "-01"
    end_date = next_month(month)

    return Transaction.query.filter(
        Transaction.user_id == user_id,
        Transaction.transaction_date >= start_date,
        Transaction.transaction_date < end_date
    ).all()


def get_month_spending(user_id, month):
    rows = get_month_transactions(user_id, month)

    return round(sum(
        float(row.amount or 0)
        for row in rows
        if row.transaction_type == "expense"
    ), 2)


def get_overall_budget(user_id, month):
    return Budget.query.filter_by(
        user_id=user_id,
        category=OVERALL_BUDGET_CATEGORY,
        month=month
    ).first()


def get_budget_context(user_id, month):
    """Calculate monthly spending and budget data safely."""

    rows = get_month_transactions(user_id, month)
    spent_by_category = {}

    for row in rows:
        if row.transaction_type == "expense":
            category = row.category or "Other"

            spent_by_category[category] = (
                spent_by_category.get(category, 0)
                + float(row.amount or 0)
            )

    spent = round(sum(spent_by_category.values()), 2)

    budget = get_overall_budget(user_id, month)

    if budget is not None:
        budget_amount = float(budget.amount or 0)
        remaining = round(budget_amount - spent, 2)
    else:
        remaining = 0.0

    budget_rows = Budget.query.filter_by(
        user_id=user_id,
        month=month
    ).order_by(Budget.category).all()

    return {
        "budget": budget,
        "spent": spent,
        "remaining": remaining,
        "spent_by_category": spent_by_category,
        "budgets": budget_rows
    }


def add_record(
    user_id,
    account_type,
    kind,
    amount,
    category,
    note="",
    transaction_date=None
):
    record = Transaction(
        user_id=user_id,
        account_type=account_type,
        transaction_type=kind,
        amount=amount,
        category=category or "Other",
        note=(note or "")[:250],
        transaction_date=(
            transaction_date or date.today().isoformat()
        )
    )

    db.session.add(record)
    return record


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user_id = session.get("user_id")

        if not user_id:
            return redirect(url_for("login"))

        user = db.session.get(User, user_id)

        if user is None:
            session.clear()
            flash(
                "Please log in again to continue.",
                "error"
            )
            return redirect(url_for("login"))

        session["username"] = user.username

        return view(*args, **kwargs)

    return wrapper


# -------------------- HOME --------------------

@app.route("/")
def index():
    if session.get("user_id"):
        user = db.session.get(User, session["user_id"])

        if user:
            return redirect(url_for("dashboard"))

        session.clear()

    return redirect(url_for("login"))


# -------------------- REGISTER --------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        user = db.session.get(User, session["user_id"])

        if user:
            return redirect(url_for("dashboard"))

        session.clear()

    if request.method == "POST":
        username = request.form.get(
            "username", ""
        ).strip()

        password = request.form.get("password", "")
        confirm_password = request.form.get(
            "confirm_password", ""
        )

        if not re.fullmatch(
            r"[A-Za-z0-9_.-]{3,80}",
            username
        ):
            flash(
                "Username must be 3–80 characters.",
                "error"
            )
            return render_template("register.html")

        if len(password) < 8:
            flash(
                "Password must have at least 8 characters.",
                "error"
            )
            return render_template("register.html")

        if password != confirm_password:
            flash(
                "Passwords do not match.",
                "error"
            )
            return render_template("register.html")

        if User.query.filter_by(
            username=username
        ).first():
            flash(
                "Username already exists. Please log in.",
                "error"
            )
            return render_template("register.html")

        try:
            user = User(
                username=username,
                password_hash=generate_password_hash(password)
            )

            db.session.add(user)
            db.session.flush()

            db.session.add(Account(
                user_id=user.id,
                main_savings=0,
                pocket_balance=0
            ))

            db.session.commit()

            session.clear()
            session["user_id"] = user.id
            session["username"] = user.username

            flash("Welcome to Spendly!", "success")

            return redirect(url_for("dashboard"))

        except Exception:
            db.session.rollback()
            app.logger.exception("Registration failed")

            flash(
                "Registration failed. Please try again.",
                "error"
            )

    return render_template("register.html")


# -------------------- LOGIN --------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        user = db.session.get(User, session["user_id"])

        if user:
            return redirect(url_for("dashboard"))

        session.clear()

    if request.method == "POST":
        username = request.form.get(
            "username", ""
        ).strip()

        password = request.form.get("password", "")

        user = User.query.filter_by(
            username=username
        ).first()

        if user and check_password_hash(
            user.password_hash,
            password
        ):
            session.clear()
            session["user_id"] = user.id
            session["username"] = user.username

            try:
                get_account(user.id)

            except Exception:
                db.session.rollback()
                app.logger.exception("Account loading failed")

                session.clear()

                flash(
                    "Could not load your account.",
                    "error"
                )

                return redirect(url_for("login"))

            flash("Login successful.", "success")

            return redirect(url_for("dashboard"))

        flash(
            "Incorrect username or password.",
            "error"
        )

    return render_template("login.html")


# -------------------- LOGOUT --------------------

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()

    flash(
        "You have been logged out.",
        "success"
    )

    return redirect(url_for("login"))


# -------------------- DASHBOARD --------------------

@app.route("/dashboard")
@login_required
def dashboard():
    user_id = session["user_id"]

    today = date.today().isoformat()
    month = date.today().strftime("%Y-%m")

    account = get_account(user_id)

    rows = get_month_transactions(user_id, month)

    monthly_income = round(sum(
        float(row.amount or 0)
        for row in rows
        if row.transaction_type == "income"
    ), 2)

    monthly_expenses = round(sum(
        float(row.amount or 0)
        for row in rows
        if row.transaction_type == "expense"
    ), 2)

    this_month_balance = round(
        monthly_income - monthly_expenses,
        2
    )

    # Total Money = Available Money + Total Savings
    available_money = float(
        account.pocket_balance or 0
    )

    total_savings = float(
        account.main_savings or 0
    )

    total_money = round(
        available_money + total_savings,
        2
    )

    # Recent transactions
    recent = (
        Transaction.query
        .filter_by(user_id=user_id)
        .order_by(
            Transaction.transaction_date.desc(),
            Transaction.id.desc()
        )
        .limit(10)
        .all()
    )

    # Spending by category
    category_totals = {}

    for row in rows:
        if row.transaction_type == "expense":
            category = row.category or "Other"

            category_totals[category] = (
                category_totals.get(category, 0)
                + float(row.amount or 0)
            )

    budget_context = get_budget_context(
        user_id,
        month
    )

    # Four weekly groups for the current month.
    # Week 4 includes all remaining days of the month.
    days_in_month = calendar.monthrange(
        date.today().year,
        date.today().month
    )[1]

    week_ranges = [
        (1, 7),
        (8, 14),
        (15, 21),
        (22, days_in_month)
    ]

    weekly_summary = []

    for week_number, (week_start, week_end) in enumerate(
        week_ranges,
        start=1
    ):
        weekly_income = 0.0
        weekly_expenses = 0.0

        for row in rows:
            try:
                row_day = date.fromisoformat(
                    row.transaction_date
                ).day

            except (ValueError, TypeError):
                continue

            if week_start <= row_day <= week_end:
                if row.transaction_type == "income":
                    weekly_income += float(
                        row.amount or 0
                    )

                elif row.transaction_type == "expense":
                    weekly_expenses += float(
                        row.amount or 0
                    )

        weekly_summary.append({
            "label": f"Week {week_number}",
            "range": f"{week_start}–{week_end}",
            "income": round(weekly_income, 2),
            "expenses": round(weekly_expenses, 2),
            "balance": round(
                weekly_income - weekly_expenses,
                2
            )
        })

    return render_template(
        "dashboard.html",
        account=account,
        today=today,
        month=month,
        monthly_income=monthly_income,
        monthly_expenses=monthly_expenses,
        this_month_balance=this_month_balance,
        monthly_balance=this_month_balance,
        total_money=total_money,
        available_money=available_money,
        total_savings=total_savings,
        recent=recent,
        categories=CATEGORIES,
        expense_categories=EXPENSE_CATEGORIES,
        income_categories=INCOME_CATEGORIES,
        category_totals=category_totals,
        spending_overview=category_totals,
        weekly_summary=weekly_summary,
        budget=budget_context["budget"],
        spent=budget_context["spent"],
        remaining=budget_context["remaining"],
        spent_by_category=budget_context["spent_by_category"],
        budgets=budget_context["budgets"]
    )


# -------------------- ADD TRANSACTION --------------------

# -------------------- ADD TRANSACTION --------------------

@app.route("/transaction/add", methods=["POST"])
@login_required
def add_transaction():
    user_id = session["user_id"]

    # Account selection is removed.
    # Expenses use the combined total of available money and savings.
    account_type = "pocket"

    kind = request.form.get("transaction_type", "")
    category = request.form.get("category", "Other").strip()
    custom_category = request.form.get("custom_category", "").strip()
    note = request.form.get("note", "").strip()

    transaction_date = request.form.get(
        "transaction_date",
        date.today().isoformat()
    )

    amount = parse_amount(request.form.get("amount"))

    if amount is None:
        flash("Please enter a valid amount.", "error")
        return redirect(url_for("transactions"))

    if kind not in ("income", "expense"):
        flash("Please select income or expense.", "error")
        return redirect(url_for("transactions"))

    if not valid_date(transaction_date):
        flash("Please select a valid date.", "error")
        return redirect(url_for("transactions"))

    if category.lower() == "custom":
        category = custom_category

    if not category:
        category = "Other"

    if len(category) > 80:
        flash("Category must be 80 characters or fewer.", "error")
        return redirect(url_for("transactions"))

    account = get_account(user_id)

    try:
        available = float(account.pocket_balance or 0)
        savings = float(account.main_savings or 0)

        total_money = round(available + savings, 2)

        # Do not allow spending more than the total balance.
        if kind == "expense" and amount > total_money:
            flash(
                "Not enough total money. Add money to your wallet first.",
                "error"
            )
            return redirect(url_for("transactions"))

        if kind == "income":
            # Income increases total money.
            account.pocket_balance = round(
                available + amount, 2
            )

        else:
            # Deduct from available money first.
            from_available = min(available, amount)

            # Deduct any remaining expense from savings.
            remaining_expense = round(
                amount - from_available, 2
            )

            account.pocket_balance = round(
                available - from_available, 2
            )

            account.main_savings = round(
                savings - remaining_expense, 2
            )

        add_record(
            user_id=user_id,
            account_type=account_type,
            kind=kind,
            amount=amount,
            category=category,
            note=note,
            transaction_date=transaction_date
        )

        db.session.commit()

        flash("Transaction saved successfully.", "success")

    except Exception:
        db.session.rollback()
        app.logger.exception("Transaction save failed")

        flash("Could not save the transaction.", "error")

    return redirect(url_for("transactions"))

# -------------------- EDIT TRANSACTION --------------------

@app.route(
    "/transaction/<int:transaction_id>/edit",
    methods=["POST"]
)
@login_required
def edit_transaction(transaction_id):
    transaction = Transaction.query.filter_by(
        id=transaction_id,
        user_id=session["user_id"]
    ).first_or_404()

    if transaction.transaction_type not in (
        "income",
        "expense"
    ):
        flash(
            "Transfer records cannot be edited here.",
            "error"
        )
        return redirect(url_for("transactions"))

    new_amount = parse_amount(
        request.form.get("amount")
    )

    new_kind = request.form.get(
        "transaction_type",
        transaction.transaction_type
    )

    new_category = request.form.get(
        "category",
        transaction.category
    ).strip()

    new_note = request.form.get(
        "note",
        transaction.note
    ).strip()

    new_date = request.form.get(
        "transaction_date",
        transaction.transaction_date
    )

    new_account_type = request.form.get(
        "account_type",
        transaction.account_type
    )

    new_field = account_field(new_account_type)

    if new_amount is None or new_field is None:
        flash(
            "Please enter a valid amount and account.",
            "error"
        )
        return redirect(url_for("transactions"))

    if (
        new_kind not in ("income", "expense")
        or not valid_date(new_date)
    ):
        flash(
            "Please check the transaction type and date.",
            "error"
        )
        return redirect(url_for("transactions"))

    if not new_category:
        new_category = "Other"

    account = get_account(
        session["user_id"]
    )

    old_field = account_field(
        transaction.account_type
    )

    try:
        # Reverse the old transaction first.
        if old_field:
            old_balance = float(
                getattr(account, old_field) or 0
            )

            if transaction.transaction_type == "income":
                old_balance -= float(
                    transaction.amount
                )
            else:
                old_balance += float(
                    transaction.amount
                )

            setattr(
                account,
                old_field,
                round(old_balance, 2)
            )

        # Apply the updated transaction.
        new_balance = float(
            getattr(account, new_field) or 0
        )

        if (
            new_kind == "expense"
            and new_amount > new_balance
        ):
            db.session.rollback()

            flash(
                "Not enough money in the selected account.",
                "error"
            )

            return redirect(url_for("transactions"))

        if new_kind == "income":
            new_balance += new_amount
        else:
            new_balance -= new_amount

        setattr(
            account,
            new_field,
            round(new_balance, 2)
        )

        transaction.account_type = new_account_type
        transaction.transaction_type = new_kind
        transaction.amount = new_amount
        transaction.category = new_category[:80]
        transaction.note = new_note[:250]
        transaction.transaction_date = new_date

        db.session.commit()

        flash(
            "Transaction updated successfully.",
            "success"
        )

    except Exception:
        db.session.rollback()
        app.logger.exception("Transaction update failed")

        flash(
            "Could not update the transaction.",
            "error"
        )

    return redirect(url_for("transactions"))


# -------------------- DELETE TRANSACTION --------------------

@app.route(
    "/transaction/<int:transaction_id>/delete",
    methods=["POST"]
)
@login_required
def delete_transaction(transaction_id):
    transaction = Transaction.query.filter_by(
        id=transaction_id,
        user_id=session["user_id"]
    ).first_or_404()

    account = get_account(
        session["user_id"]
    )

    try:
        field = account_field(
            transaction.account_type
        )

        if (
            field
            and transaction.transaction_type in (
                "income",
                "expense"
            )
        ):
            balance = float(
                getattr(account, field) or 0
            )

            if transaction.transaction_type == "income":
                balance -= float(
                    transaction.amount
                )
            else:
                balance += float(
                    transaction.amount
                )

            setattr(
                account,
                field,
                round(balance, 2)
            )

        db.session.delete(transaction)
        db.session.commit()

        flash(
            "Transaction deleted successfully.",
            "success"
        )

    except Exception:
        db.session.rollback()
        app.logger.exception("Transaction deletion failed")

        flash(
            "Could not delete the transaction.",
            "error"
        )

    return redirect(url_for("transactions"))


# -------------------- TRANSFERS --------------------

@app.route("/transfer", methods=["POST"])
@login_required
def transfer():
    user_id = session["user_id"]

    direction = request.form.get(
        "direction",
        ""
    )

    amount = parse_amount(
        request.form.get("amount")
    )

    if amount is None:
        flash(
            "Enter a valid transfer amount.",
            "error"
        )
        return redirect(url_for("dashboard"))

    if direction == "to_pocket":
        source_field = "main_savings"
        destination_field = "pocket_balance"
        source_name = "savings"
        destination_name = "pocket"

    elif direction == "to_savings":
        source_field = "pocket_balance"
        destination_field = "main_savings"
        source_name = "pocket"
        destination_name = "savings"

    else:
        flash(
            "Invalid transfer selection.",
            "error"
        )
        return redirect(url_for("dashboard"))

    account = get_account(user_id)

    source_balance = float(
        getattr(account, source_field) or 0
    )

    if amount > source_balance:
        flash(
            "Insufficient balance for this transfer.",
            "error"
        )
        return redirect(url_for("dashboard"))

    try:
        setattr(
            account,
            source_field,
            round(source_balance - amount, 2)
        )

        destination_balance = float(
            getattr(account, destination_field) or 0
        )

        setattr(
            account,
            destination_field,
            round(destination_balance + amount, 2)
        )

        today = date.today().isoformat()

        add_record(
            user_id,
            source_name,
            "transfer_out",
            amount,
            "Transfer",
            "Transfer sent",
            today
        )

        add_record(
            user_id,
            destination_name,
            "transfer_in",
            amount,
            "Transfer",
            "Transfer received",
            today
        )

        db.session.commit()

        flash(
            "Transfer completed successfully.",
            "success"
        )

    except Exception:
        db.session.rollback()
        app.logger.exception("Transfer failed")

        flash(
            "Transfer failed. Please try again.",
            "error"
        )

    return redirect(url_for("dashboard"))


# -------------------- WALLET: ADD MONEY --------------------

@app.route("/wallet/add-money", methods=["POST"])
@login_required
def add_wallet_money():
    amount = parse_amount(
        request.form.get("amount")
    )

    if amount is None:
        flash(
            "Enter a valid amount.",
            "error"
        )
        return redirect(url_for("dashboard"))

    account = get_account(
        session["user_id"]
    )

    try:
        account.pocket_balance = round(
            float(account.pocket_balance or 0) + amount,
            2
        )

        db.session.commit()

        flash(
            "Money added to your available wallet balance.",
            "success"
        )

    except Exception:
        db.session.rollback()
        app.logger.exception("Wallet top-up failed")

        flash(
            "Could not update your wallet.",
            "error"
        )

    return redirect(url_for("dashboard"))


# -------------------- WALLET: ADD SAVINGS --------------------

@app.route("/wallet/add-savings", methods=["POST"])
@login_required
def add_wallet_savings():
    amount = parse_amount(
        request.form.get("amount")
    )

    if amount is None:
        flash(
            "Enter a valid savings amount.",
            "error"
        )
        return redirect(url_for("dashboard"))

    account = get_account(
        session["user_id"]
    )

    available = float(
        account.pocket_balance or 0
    )

    if amount > available:
        flash(
            "Savings amount cannot exceed available money.",
            "error"
        )
        return redirect(url_for("dashboard"))

    try:
        account.pocket_balance = round(
            available - amount,
            2
        )

        account.main_savings = round(
            float(account.main_savings or 0) + amount,
            2
        )

        today = date.today().isoformat()

        add_record(
            session["user_id"],
            "pocket",
            "transfer_out",
            amount,
            "Savings Transfer",
            "Moved from available money to savings",
            today
        )

        add_record(
            session["user_id"],
            "savings",
            "transfer_in",
            amount,
            "Savings Transfer",
            "Added to savings",
            today
        )

        db.session.commit()

        flash(
            "Money moved to savings successfully.",
            "success"
        )

    except Exception:
        db.session.rollback()
        app.logger.exception("Savings transfer failed")

        flash(
            "Could not add to savings.",
            "error"
        )

    return redirect(url_for("dashboard"))


# -------------------- TRANSACTIONS PAGE --------------------

@app.route("/transactions")
@login_required
def transactions():
    user_id = session["user_id"]
    month = selected_month()

    search = request.args.get(
        "search",
        ""
    ).strip()

    type_filter = request.args.get(
        "type",
        request.args.get("type_filter", "")
    ).strip()

    category_filter = request.args.get(
        "category",
        request.args.get("category_filter", "")
    ).strip()

    query = Transaction.query.filter(
        Transaction.user_id == user_id,
        Transaction.transaction_date >= month + "-01",
        Transaction.transaction_date < next_month(month)
    )

    if type_filter in ("income", "expense"):
        query = query.filter(
            Transaction.transaction_type == type_filter
        )

    if category_filter:
        query = query.filter(
            Transaction.category == category_filter
        )

    if search:
        pattern = f"%{search}%"

        query = query.filter(or_(
            Transaction.category.ilike(pattern),
            Transaction.note.ilike(pattern),
            Transaction.transaction_type.ilike(pattern)
        ))

    rows = query.order_by(
        Transaction.transaction_date.desc(),
        Transaction.id.desc()
    ).all()

    budget_context = get_budget_context(
        user_id,
        month
    )

    return render_template(
        "transactions.html",
        transactions=rows,
        today=date.today().isoformat(),
        month=month,
        search=search,
        type_filter=type_filter,
        category_filter=category_filter,
        categories=ALL_CATEGORIES,
        expense_categories=EXPENSE_CATEGORIES,
        income_categories=INCOME_CATEGORIES,
        budget=budget_context["budget"],
        spent=budget_context["spent"],
        remaining=budget_context["remaining"],
        budgets=budget_context["budgets"],
        spent_by_category=budget_context["spent_by_category"]
    )


# -------------------- BUDGETS PAGE --------------------

@app.route("/budgets", methods=["GET", "POST"])
@login_required
def budgets():
    user_id = session["user_id"]
    month = selected_month()

    if request.method == "POST":
        month = request.form.get(
            "month",
            month
        )

        amount = parse_amount(
            request.form.get(
                "amount",
                request.form.get("budget_amount")
            )
        )

        category = request.form.get(
            "category",
            OVERALL_BUDGET_CATEGORY
        ).strip()

        if not valid_month(month):
            flash(
                "Please select a valid month.",
                "error"
            )
            return redirect(url_for("budgets"))

        if amount is None:
            flash(
                "Enter a valid budget amount.",
                "error"
            )
            return redirect(
                url_for("budgets", month=month)
            )

        if not category:
            category = OVERALL_BUDGET_CATEGORY

        if (
            category != OVERALL_BUDGET_CATEGORY
            and category not in EXPENSE_CATEGORIES
        ):
            flash(
                "Please select a valid budget category.",
                "error"
            )
            return redirect(
                url_for("budgets", month=month)
            )

        try:
            budget_record = Budget.query.filter_by(
                user_id=user_id,
                category=category,
                month=month
            ).first()

            if budget_record is None:
                budget_record = Budget(
                    user_id=user_id,
                    category=category,
                    month=month,
                    amount=amount
                )

                db.session.add(budget_record)

            else:
                budget_record.amount = amount

            db.session.commit()

            flash(
                "Budget saved successfully.",
                "success"
            )

        except Exception:
            db.session.rollback()
            app.logger.exception("Budget save failed")

            flash(
                "Could not save the budget.",
                "error"
            )

        return redirect(
            url_for("budgets", month=month)
        )

    budget_context = get_budget_context(
        user_id,
        month
    )

    return render_template(
        "budgets.html",
        month=month,
        budget=budget_context["budget"],
        spent=budget_context["spent"],
        remaining=budget_context["remaining"],
        budgets=budget_context["budgets"],
        spent_by_category=budget_context["spent_by_category"],
        categories=EXPENSE_CATEGORIES,
        overall_budget_category=OVERALL_BUDGET_CATEGORY
    )


# -------------------- REPORTS PAGE --------------------

@app.route("/reports")
@login_required
def reports():
    user_id = session["user_id"]
    month = selected_month()

    rows = get_month_transactions(
        user_id,
        month
    )

    category_totals = {}
    monthly_income = 0.0
    monthly_expenses = 0.0

    for transaction in rows:
        amount = float(
            transaction.amount or 0
        )

        if transaction.transaction_type == "income":
            monthly_income += amount

        elif transaction.transaction_type == "expense":
            monthly_expenses += amount

            category = transaction.category or "Other"

            category_totals[category] = (
                category_totals.get(category, 0) + amount
            )

    budget_context = get_budget_context(
        user_id,
        month
    )

    return render_template(
        "reports.html",
        month=month,
        category_totals=category_totals,
        monthly_income=round(monthly_income, 2),
        monthly_expenses=round(monthly_expenses, 2),
        budget=budget_context["budget"],
        spent=budget_context["spent"],
        remaining=budget_context["remaining"]
    )


# -------------------- CSV EXPORT --------------------

@app.route("/export.csv")
@login_required
def export_csv():
    rows = (
        Transaction.query
        .filter_by(user_id=session["user_id"])
        .order_by(
            Transaction.transaction_date.desc(),
            Transaction.id.desc()
        )
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Date",
        "Account",
        "Type",
        "Amount",
        "Category",
        "Note"
    ])

    for item in rows:
        writer.writerow([
            item.transaction_date,
            item.account_type,
            item.transaction_type,
            item.amount,
            item.category,
            item.note
        ])

    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
                "attachment; filename=spendly_transactions.csv"
        }
    )


# -------------------- DATABASE INITIALIZATION --------------------

with app.app_context():
    db.create_all()


# -------------------- RUN APP --------------------

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
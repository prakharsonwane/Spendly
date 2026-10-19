from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(
        db.String(80),
        unique=True,
        nullable=False,
        index=True
    )
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )


class Account(db.Model):
    __tablename__ = "accounts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        unique=True,
        nullable=False
    )

    # Main savings and pocket money are kept separate.
    main_savings = db.Column(db.Float, default=0.0, nullable=False)
    pocket_balance = db.Column(db.Float, default=0.0, nullable=False)


class Transaction(db.Model):
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    # Expected values: main_savings or pocket_balance
    account_type = db.Column(db.String(30), nullable=False)

    # Expected values: income, expense, transfer_in, transfer_out
    transaction_type = db.Column(db.String(30), nullable=False)

    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(80), default="Other", nullable=False)
    note = db.Column(db.String(250), default="", nullable=False)

    # ISO date string, e.g. 2026-10-19
    transaction_date = db.Column(db.String(10), nullable=False, index=True)

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )


class Budget(db.Model):
    __tablename__ = "budgets"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    category = db.Column(db.String(80), nullable=False)
    month = db.Column(db.String(7), nullable=False)  # YYYY-MM
    amount = db.Column(db.Float, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "category",
            "month",
            name="unique_user_category_month"
        ),
    )
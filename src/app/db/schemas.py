from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Any

from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, JSON, Numeric, CheckConstraint


class Aircraft(SQLModel, table=True):
    __tablename__ = "aircrafts_data"
    __table_args__ = (CheckConstraint("range > 0", name="aircrafts_range_check"),)

    aircraft_code: str = Field(primary_key=True, max_length=3)
    model: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    range: int = Field(nullable=False)

    seats: List["Seat"] = Relationship(back_populates="aircraft")
    flights: List["Flight"] = Relationship(back_populates="aircraft")


class Airport(SQLModel, table=True):
    __tablename__ = "airports_data"

    airport_code: str = Field(primary_key=True, max_length=3)
    airport_name: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    city: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    coordinates: str = Field(nullable=False)  # SQLite-safe placeholder for point
    timezone: str = Field(nullable=False)

    departures: List["Flight"] = Relationship(
        back_populates="departure_airport_rel",
        sa_relationship_kwargs={"foreign_keys": "[Flight.departure_airport]"},
    )
    arrivals: List["Flight"] = Relationship(
        back_populates="arrival_airport_rel",
        sa_relationship_kwargs={"foreign_keys": "[Flight.arrival_airport]"},
    )


class Booking(SQLModel, table=True):
    __tablename__ = "bookings"

    book_ref: str = Field(primary_key=True, max_length=6)
    book_date: datetime = Field(nullable=False)
    total_amount: Decimal = Field(sa_column=Column(Numeric(10, 2), nullable=False))

    tickets: List["Ticket"] = Relationship(back_populates="booking")


class Ticket(SQLModel, table=True):
    __tablename__ = "tickets"

    ticket_no: str = Field(primary_key=True, max_length=13)
    book_ref: str = Field(foreign_key="bookings.book_ref", max_length=6, nullable=False)
    passenger_id: str = Field(max_length=20, nullable=False)

    booking: Optional[Booking] = Relationship(back_populates="tickets")
    ticket_flights: List["TicketFlight"] = Relationship(back_populates="ticket")
    boarding_passes: List["BoardingPass"] = Relationship(back_populates="ticket")


class Flight(SQLModel, table=True):
    __tablename__ = "flights"

    flight_id: int = Field(primary_key=True)

    flight_no: str = Field(max_length=6, nullable=False)
    scheduled_departure: datetime = Field(nullable=False)
    scheduled_arrival: datetime = Field(nullable=False)

    departure_airport: str = Field(
        foreign_key="airports_data.airport_code", max_length=3, nullable=False
    )
    arrival_airport: str = Field(
        foreign_key="airports_data.airport_code", max_length=3, nullable=False
    )

    status: str = Field(max_length=20, nullable=False)
    aircraft_code: str = Field(
        foreign_key="aircrafts_data.aircraft_code", max_length=3, nullable=False
    )

    actual_departure: Optional[datetime] = None
    actual_arrival: Optional[datetime] = None

    aircraft: Optional[Aircraft] = Relationship(back_populates="flights")
    departure_airport_rel: Optional[Airport] = Relationship(
        back_populates="departures",
        sa_relationship_kwargs={"foreign_keys": "[Flight.departure_airport]"},
    )
    arrival_airport_rel: Optional[Airport] = Relationship(
        back_populates="arrivals",
        sa_relationship_kwargs={"foreign_keys": "[Flight.arrival_airport]"},
    )

    ticket_flights: List["TicketFlight"] = Relationship(back_populates="flight")
    boarding_passes: List["BoardingPass"] = Relationship(back_populates="flight")


class Seat(SQLModel, table=True):
    __tablename__ = "seats"

    aircraft_code: str = Field(
        foreign_key="aircrafts_data.aircraft_code",
        primary_key=True,
        max_length=3,
    )
    seat_no: str = Field(primary_key=True, max_length=4)
    fare_conditions: str = Field(max_length=10, nullable=False)

    aircraft: Optional[Aircraft] = Relationship(back_populates="seats")


class TicketFlight(SQLModel, table=True):
    __tablename__ = "ticket_flights"

    ticket_no: str = Field(
        foreign_key="tickets.ticket_no",
        primary_key=True,
        max_length=13,
    )
    flight_id: int = Field(foreign_key="flights.flight_id", primary_key=True)
    fare_conditions: str = Field(max_length=10, nullable=False)
    amount: Decimal = Field(sa_column=Column(Numeric(10, 2), nullable=False))

    ticket: Optional[Ticket] = Relationship(back_populates="ticket_flights")
    flight: Optional[Flight] = Relationship(back_populates="ticket_flights")


class BoardingPass(SQLModel, table=True):
    __tablename__ = "boarding_passes"

    ticket_no: str = Field(
        foreign_key="tickets.ticket_no",
        primary_key=True,
        max_length=13,
    )
    flight_id: int = Field(foreign_key="flights.flight_id", primary_key=True)
    boarding_no: int = Field(nullable=False)
    seat_no: str = Field(max_length=4, nullable=False)

    ticket: Optional[Ticket] = Relationship(back_populates="boarding_passes")
    flight: Optional[Flight] = Relationship(back_populates="boarding_passes")

from app.capabilities.capability import Capability, CapabilityRegistry
from app.capabilities.booking.capability import BookingCapability

booking_capability = Capability(
    id="booking",
    description=(
        "Retrieve bookings by reference, search bookings by date or date range, "
        "calculate booking counts, total amounts, and revenue for a period, "
        "create new bookings with a reference, date, and total amount, and "
        "delete bookings after checking dependencies."
    ),

)
flight_capability = Capability(
    id="flight",
    description=(
        "Retrieve flights by ID or flight number, find flights between departure "
        "and arrival airports, show and analyze flight status and timing "
        "(scheduled, delayed, cancelled, or arrived), identify the assigned "
        "aircraft, and analyze popular routes and related revenue."
    ),
)

ticket_capability = Capability(
    id="ticket",
    description=(
        "Retrieve ticket details by ticket number, find tickets by passenger ID, "
        "retrieve flights associated with a ticket, create tickets for an existing "
        "booking reference, delete tickets after dependency checks, and analyze "
        "fare conditions and ticket amounts."
    ),
)

airport_capability = Capability(
    id="airport",
    description=(
        "Retrieve airports by airport code or city, display airport name, city, "
        "coordinates, and time zone, find incoming and outgoing flights, and "
        "resolve an airport's origin or destination city/location for weather queries."
    ),
)

weather_capability = Capability(
    id="weather",
    description=(
        "Retrieve current weather for a flight's departure or destination location, "
        "use airport information to resolve the relevant city or location when needed, "
        "and combine weather results with flight details."
    ),
)

registery = CapabilityRegistry()

registery.register(BookingCapability())


# registery.register(booking_capability)
# registery.register(flight_capability)
# registery.register(ticket_capability)
# registery.register(airport_capability)
# registery.register(weather_capability)

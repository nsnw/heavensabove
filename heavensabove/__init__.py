__version__ = '0.1.0'

import requests
import logging
import re
import pytz
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import List

logger = logging.getLogger(__name__)

BASE_URL = 'https://www.heavens-above.com'
UTC = pytz.timezone('UTC')
EPOCH = datetime(1, 1, 1, 0, 0, 0, 0, UTC)


def _utc_now() -> datetime:
    """ Return the current UTC time """
    return datetime.now().astimezone(UTC)


def _to_timestamp(timestamp: datetime) -> int:
    """
    Convert a datetime object to a integer representing the number of microseconds(?) since
    January 1st 0001.

    :param datetime timestamp: a datetime object
    :return: number of microseconds since January 1st 0001
    """
    delta = timestamp - EPOCH
    return int(delta.total_seconds() * 10000000)


def _make_timestamp(day: str, month: str, timestamp: str, newer_than: datetime = None) -> datetime:
    """
    Given a day, month and time, generate a datetime object.

    The year is initially assumed to be the same as the current year. If this results in a date
    that is more than one day in the past, assume it's for next year.

    An optional datetime object can also be passed. If passed, and the generated timestamp is older
    than the passed timestamp, a day is added to the generated timestamp.

    :param str day: the day (as digits - e.g. 27)
    :param str month: the month (in abbreviated format - e.g. Dec)
    :param str timestamp: the time (in HH:MM format)
    :param datetime newer_than: an optional timestamp to compare to
    :return: a generated datetime object
    """
    # Build a datetime object based on the the passed values
    ts = datetime.strptime(
        "{} {} {} {} UTC".format(
            month, day, _utc_now().year, timestamp
        ),
        "%b %d %Y %H:%M:%S %Z"
    )

    # This timestamp is in UTC, so make sure our datetime object is not naive
    ts = pytz.utc.localize(ts)

    # Get the timestamp for yesterday ('now' minus one day)
    yesterday = _utc_now() - timedelta(days=1)

    # If an optional timestamp was passed, check to see if the generated timestamp is older.
    # Otherwise, check to see if the generated timestamp is more than a day in the past.
    if newer_than and ts < newer_than:
        # Generated timestamp is older, so subtract a day
        ts = ts + timedelta(days=1)

    elif ts < yesterday:
        # Generated timestamp is more than a day in the past, so assume the date is for next year
        ts = ts.replace(year=ts.year + 1)

    return ts


class HeavensAboveError(Exception):
    """ Generic exception for raising errors. """

    def __init__(self, *args, **kwargs):
        super(HeavensAboveError, self).__init__(*args, **kwargs)


class Position:
    """ Class representing a satellite position. """

    _timestamp = None
    _altitude = None
    _direction = None
    _direction_degrees = None
    _distance = None
    _brightness = None
    _sun_altitude = None

    def __init__(self, timestamp: datetime, altitude: int, direction: str):
        self._timestamp = timestamp
        self._altitude = altitude
        self._direction = direction

    @property
    def timestamp(self) -> datetime:
        return self._timestamp

    @property
    def altitude(self) -> int:
        return self._altitude

    @property
    def direction(self) -> str:
        return self._direction

    @property
    def direction_degrees(self) -> int:
        return self._direction_degrees

    @property
    def distance(self) -> int:
        return self._distance

    @property
    def brightness(self) -> float:
        if self._brightness:
            return float(self._brightness)

    @property
    def sun_altitude(self) -> float:
        if self._sun_altitude:
            return float(self._sun_altitude)

    def __repr__(self) -> str:
        return "<{}: {}>".format(
            self.__class__.__name__,
            self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        )


class RisesPosition(Position):
    pass


class StartsPosition(Position):
    pass


class HighestPosition(Position):
    pass


class EndsPosition(Position):
    pass


class SetsPosition(Position):
    pass


class Satellite:
    """ Class to represent a satellite from the Heavens Above site. """

    # URLs
    INFO_URL = '{}/SatInfo.aspx'.format(BASE_URL)
    PASS_URL = '{}/PassSummary.aspx'.format(BASE_URL)

    _satellite_id = None
    _name = None
    _cospar_id = None
    _catalog_name = None
    _category = None

    def __init__(self, satellite_id: int, name: str) -> "Satellite":
        self._satellite_id = satellite_id
        self._name = name

    @property
    def satellite_id(self) -> int:
        """ Return the satellite ID """
        return self._satellite_id

    @property
    def name(self) -> str:
        """ Return the satellite name """
        return self._name

    @property
    def cospar_id(self) -> str:
        """ Return the COSPAR ID """
        return self._cospar_id

    @property
    def catalog_name(self) -> str:
        """ Return the Spacetrack catalog name """
        return self._catalog_name

    @property
    def category(self) -> str:
        """ Return the satellite category """
        return self._category

    @classmethod
    def get(cls, satellite_id: int) -> "Satellite":
        """ Retrieve the details for a given satellite, by ID. """

        try:
            # Retrieve details from Heavens Above
            r = requests.get(
                cls.INFO_URL,
                params={
                    'satid': satellite_id
                }
            )

            r.raise_for_status()

        except (requests.HTTPError, requests.ConnectionError) as e:
            raise HeavensAboveError(e)

        # Parse HTML
        b = BeautifulSoup(r.text, 'html.parser')

        # Get the title
        title = b.find('span', id='ctl00_lblTitle').text
        name = re.sub(r' - Satellite Information', '', title)

        # Create new Satellite object
        s = cls(satellite_id=satellite_id, name=name)

        # Get the COSPAR ID
        s._cospar_id = b.find('span', id='ctl00_cph1_lblIntDesig').text
        s._catalog_name = b.find('span', id='ctl00_cph1_lblOIGName').text
        s._category = b.find(string=re.compile("Category")).parent.next_sibling.text.rstrip()

        return s

    def passes(self, latitude: float, longitude: float, start_time_utc: datetime = None,
               show_all: bool = False) -> List["SatellitePass"]:
        """ Get the next passes for the current satellite.

        :param float latitude: the observer's latitude
        :param float longitude: the observers longitude
        :param datetime start_time_utc: the start time to search from (in UTC)
        :param bool show_all: show all passes, rather than just visible ones (defaults to False)
        :return: a list of :class:`SatellitePass` objects
        """

        # If no start time is given, assume now
        if start_time_utc is None:
            start_time_utc = _to_timestamp(_utc_now())

        # Build the parameters
        params = {
            'satid': self.satellite_id,
            'lat': latitude,
            'lng': longitude,
        }

        if show_all:
            params['showall'] = "t"

        try:
            # Make request
            r = requests.post(
                self.PASS_URL,
                params=params,
                data={
                    'utcOffset': 0,
                    'ctl00$ddlCulture': "en",
                    'ctl00$cph1$hidStartUtc': start_time_utc
                }
            )

            r.raise_for_status()

        except (requests.HTTPError, requests.ConnectionError) as e:
            raise HeavensAboveError(e)

        # Parse HTML
        b = BeautifulSoup(r.text, 'html.parser')

        # Extract passes
        passes = []

        # Iterate over each pass, and create a SatellitePass object for each
        for s_pass in b.find_all('tr', class_='clickableRow'):
            td = s_pass.find_all('td')

            # Get the details link for the pass
            link = td[0].find('a').get('href')

            # Get the day and month
            (day, month) = td[0].text.split(" ")

            # Get the brightness of the pass
            brightness = td[1].text

            # If the brightness is a -, just set it to None
            if brightness == "-":
                brightness = None

            # Parse the start time, altitude and azimuth
            start_time = td[2].text
            start_alt = re.search(r'\d+', td[3].text)[0]
            start_az = td[4].text

            # Generate a datetime object for the start
            # Assume the same year as the current date
            # If the resulting date is in the past, add a year
            start = _make_timestamp(day, month, start_time)

            # Create the position object for the start of the pass
            start_position = StartsPosition(
                timestamp=start,
                altitude=int(start_alt),
                direction=start_az
            )

            # Parse the highest time, altitude and azimuth
            highest_time = td[5].text
            highest_alt = re.search(r'\d+', td[6].text)[0]
            highest_az = td[7].text

            # Generate a datetime object for the highest point
            # Assume the same day, but if we end up with a date older than the start,
            # increment it by a day
            highest = _make_timestamp(day, month, highest_time, start)

            # Create the position object for the highest part of the pass
            highest_position = HighestPosition(
                timestamp=highest,
                altitude=int(highest_alt),
                direction=highest_az
            )

            # Parse the end time, altitude and azimuth
            end_time = td[8].text
            end_alt = re.search(r'\d+', td[9].text)[0]
            end_az = td[10].text

            # Generate a datetime object for the end
            # As with the highest time, assume the same day
            end = _make_timestamp(day, month, end_time, highest)

            # Create the position object for the end of the pass
            end_position = EndsPosition(
                timestamp=end,
                altitude=int(end_alt),
                direction=end_az
            )

            # Parse the pass type (e.g. 'visible')
            pass_type = td[11].text

            # Create the pass object
            p = SatellitePass(
                satellite=self,
                latitude=latitude,
                longitude=longitude,
                brightness=brightness,
                starts=start_position,
                highest=highest_position,
                ends=end_position,
                pass_type=pass_type,
                link=link
            )

            # Append the pass object to the list of passes
            passes.append(p)

        return passes

    def __repr__(self) -> str:
        return "<Satellite: {} ({})>".format(
            self.satellite_id, self.name
        )


class SatellitePass:
    """ Class to represent a single pass for a satellite.

    A pass will have at least a `starts`, `highest` and `ends`.
    """

    _satellite = None
    _latitude = None
    _longitude = None
    _brightness = None
    _rises = None
    _starts = None
    _highest = None
    _ends = None
    _sets = None
    _pass_type = None
    _link = None

    def __init__(self, satellite: Satellite, latitude: float, longitude: float, brightness: float,
                 starts: Position, highest: Position, ends: Position, pass_type: str, link: str):
        """ Create a new pass.

        :param Satellite satellite: the :class:`Satellite` object this pass is for
        :param float latitude: the observer's latitude
        :param float longitude: the observer's longitude
        :param Position starts: the position object for the pass's start (10 degrees above the
            horizon)
        :param Position highest: the position object for the pass's highest point
        :param Position ends: the position object for the pass's end (10 degrees above the horizon)
        :param str pass_type: the type of pass (e.g. 'visible')
        :param str link: the link to further details
        """
        self._satellite = satellite
        self._latitude = latitude
        self._longitude = longitude
        self._brightness = brightness
        self._starts = starts
        self._highest = highest
        self._ends = ends
        self._pass_type = pass_type
        self._link = link

    @property
    def satellite(self) -> Satellite:
        """ The :class:`Satellite` object this pass is for. """
        return self._satellite

    @property
    def latitude(self) -> float:
        """ The observer's latitude. """
        return float(self._latitude)

    @property
    def longitude(self) -> float:
        """ The observer's longitude. """
        return float(self._longitude)

    @property
    def brightness(self) -> float:
        """ The peak brightness of the satellite during the pass. """
        if self._brightness:
            return float(self._brightness)

    @property
    def rises(self) -> Position:
        """ A :class:`Position` object for when the satellite rises above the horizon. """
        return self._rises

    @property
    def starts(self) -> Position:
        """ A :class:`Position` object for when the satellite reaches 10 degrees above the horizon
        """
        return self._starts

    @property
    def highest(self) -> Position:
        """ A :class:`Position` object for when the satellite reaches its highest point in the sky.
        """
        return self._highest

    @property
    def ends(self) -> Position:
        """ A :class:`Position` object for when the satellite drops to 10 degrees above the horizon
        again """
        return self._ends

    @property
    def sets(self) -> Position:
        """ A :class:`Position` object for when the satellite sets below the horizon. """
        return self._sets

    @property
    def pass_type(self) -> str:
        """ The pass type (e.g. 'visible', 'daylight'). """
        return self._pass_type

    @property
    def link(self) -> str:
        """ The link to the details page. """
        return self._link

    def get_details(self) -> bool:
        """
        Query Heavens Above for further details about this pass.

        This will add the positions for the `rises` and `sets` attributes, along with the
        distance, direction (in degrees) and Sun altitude for all positions for this pass.

        :return: whether or not the request was successful.
        """
        try:
            # Make request
            r = requests.get(
                "{}/{}".format(
                    BASE_URL, self.link
                )
            )

            r.raise_for_status()

        except (requests.HTTPError, requests.ConnectionError) as e:
            raise HeavensAboveError(e)

        # Parse response
        b = BeautifulSoup(r.text, 'html.parser')

        table = b.find('tbody').find_all('tr')

        # Extract the details for each position for this pass
        rises = table[0].find_all('td')
        starts = table[1].find_all('td')
        highest = table[2].find_all('td')
        ends = table[3].find_all('td')
        sets = table[4].find_all('td')

        # Get the times for whenthis pass rises and sets
        rises_time = rises[1].text.split(':')
        sets_time = sets[1].text.split(':')

        # Build timestamps for the rises and sets times, based off the existing start timestamp
        rises_ts = self.starts.timestamp.replace(
            hour=int(rises_time[0]),
            minute=int(rises_time[1]),
            second=int(rises_time[2])
        )
        sets_ts = self.starts.timestamp.replace(
            hour=int(sets_time[0]),
            minute=int(sets_time[1]),
            second=int(sets_time[2])
        )

        # Ensure the rises timestamp is before the start timestamp, and subtract a day if so
        if rises_ts > self.starts.timestamp:
            rises_ts = rises_ts + timedelta(days=1)

        # Ensure the sets timestamp is after the end timestamp, and add a day if so
        if sets_ts < self.ends.timestamp:
            sets_ts = sets_ts - timedelta(days=1)

        # Parse the details for each position in the pass.
        (rises_degrees, rises_direction) = re.search(r'(\d+)° \((\w+)\)', rises[3].text).groups()
        rises_distance = re.sub(r'[^0-9]', "", rises[4].text)
        rises_brightness = rises[5].text
        rises_sun_altitude = re.sub(r'[^0-9\-\.]', "", rises[6].text)

        self._rises = RisesPosition(
            timestamp=rises_ts,
            altitude=0,
            direction=rises_direction
        )
        self._rises._direction_degrees = rises_degrees
        self._rises._distance = rises_distance
        self._rises._brightness = rises_brightness
        self._rises._sun_altitude = rises_sun_altitude

        (starts_degrees, starts_direction) = re.search(r'(\d+)° \((\w+)\)', starts[3].text).groups()
        starts_distance = re.sub(r'[^0-9]', "", starts[4].text)
        starts_brightness = starts[5].text
        starts_sun_altitude = re.sub(r'[^0-9\-\.]', "", starts[6].text)

        self._starts._direction_degrees = starts_degrees
        self._starts._distance = starts_distance
        self._starts._brightness = starts_brightness
        self._starts._sun_altitude = starts_sun_altitude

        (highest_degrees, highest_direction) = re.search(
            r'(\d+)° \((\w+)\)', highest[3].text
        ).groups()
        highest_distance = re.sub(r'[^0-9]', "", highest[4].text)
        highest_brightness = highest[5].text
        highest_sun_altitude = re.sub(r'[^0-9\-\.]', "", highest[6].text)

        self._highest._direction_degrees = highest_degrees
        self._highest._distance = highest_distance
        self._highest._brightness = highest_brightness
        self._highest._sun_altitude = highest_sun_altitude

        (ends_degrees, ends_direction) = re.search(r'(\d+)° \((\w+)\)', ends[3].text).groups()
        ends_distance = re.sub(r'[^0-9]', "", ends[4].text)
        ends_brightness = ends[5].text
        ends_sun_altitude = re.sub(r'[^0-9\-\.]', "", ends[6].text)

        self._ends._direction_degrees = ends_degrees
        self._ends._distance = ends_distance
        self._ends._brightness = ends_brightness
        self._ends._sun_altitude = ends_sun_altitude

        (sets_degrees, sets_direction) = re.search(r'(\d+)° \((\w+)\)', sets[3].text).groups()
        sets_distance = re.sub(r'[^0-9]', "", sets[4].text)
        sets_brightness = sets[5].text
        sets_sun_altitude = re.sub(r'[^0-9\-\.]', "", sets[6].text)

        self._sets = SetsPosition(
            timestamp=sets_ts,
            altitude=0,
            direction=sets_direction
        )
        self._sets._direction_degrees = sets_degrees
        self._sets._distance = sets_distance
        self._sets._brightness = sets_brightness
        self._sets._sun_altitude = sets_sun_altitude

    def __repr__(self) -> str:
        return "<SatellitePass: {} ({})>".format(
            self.satellite.name,
            self.starts.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        )

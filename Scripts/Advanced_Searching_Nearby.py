import requests
import json
import math
import pandas as pd
import csv
import time
from colorama import Fore, Style
import folium
from folium import plugins
import branca.colormap as cm

class SearchArea:
    def __init__(self):
        self.rectangles = []  # List of tuples: (coords, results_count, was_subdivided)

    def add_rectangle(self, coords, results_count, was_subdivided):
        self.rectangles.append((coords, results_count, was_subdivided))

class PlacesAPIUtil:
    """
    A utility class for interacting with the Google Places API to search for places
    within specified geographic areas, handling pagination, and saving results.
    """

    def __init__(self, api_key):
        """
        Initializes the PlacesAPIUtil with your Google Places API key.

        Args:
            api_key (str): Your Google Places API key.
        """
        self.api_key = api_key
        self.search_area = SearchArea()
        self.url = "https://places.googleapis.com/v1/places:searchNearby"
        self.headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "*"
        }


    def haversine_distance(self, lat1, lon1, lat2, lon2):
        """Calculates the distance between two points on Earth using the Haversine formula."""
        R = 6371  # Earth radius in kilometers

        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        return R * c

    def get_rectangle_center_and_radius(self, sw_lat, sw_lon, ne_lat, ne_lon):
        """Calculates the center and approximate radius (half the diagonal) of a rectangle."""
        center_lat = (sw_lat + ne_lat) / 2
        center_lon = (sw_lon + ne_lon) / 2
        diagonal = self.haversine_distance(sw_lat, sw_lon, ne_lat, ne_lon)
        approx_radius = diagonal / 2
        return center_lat, center_lon, approx_radius

    def subdivide_rectangle(self, sw_lat, sw_lon, ne_lat, ne_lon, divisions):
        """Divides a rectangle into a grid of smaller rectangles."""
        lat_step = (ne_lat - sw_lat) / divisions
        lon_step = (ne_lon - sw_lon) / divisions
        rectangles = []

        for i in range(divisions):
            for j in range(divisions):
                rect_sw_lat = sw_lat + i * lat_step
                rect_sw_lon = sw_lon + j * lon_step
                rect_ne_lat = sw_lat + (i + 1) * lat_step
                rect_ne_lon = sw_lon + (j + 1) * lon_step
                rectangles.append((rect_sw_lat, rect_sw_lon, rect_ne_lat, rect_ne_lon))

        return rectangles

    def _make_request(self, latitude, longitude, radius, included_types, page_token= None):
        """Makes a single request to the Google Places API."""
        payload = {
            "includedTypes": included_types,
            "maxResultCount": 20,
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": latitude,
                        "longitude": longitude
                    },
                    "radius": radius  # Radius in meters
                }
            }
        }

        if page_token:
            payload["pageToken"] = page_token

        try:
            print(f"{Fore.YELLOW}Making request with payload: {json.dumps(payload, indent=2)}{Style.RESET_ALL}")
            response = requests.post(self.url, headers=self.headers, json=payload)
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

            print(f"{Fore.YELLOW}Response status: {response.status_code}{Style.RESET_ALL}")
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"{Fore.RED}Request Error: {e}{Style.RESET_ALL}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"{Fore.RED}Error response: {e.response.text}{Style.RESET_ALL}")
            return None


    def _get_all_pages_results(self, latitude, longitude, radius, included_types):
        """Retrieves all results from the API, handling pagination (up to 3 pages)."""
        results = []
        payload = {
            "includedTypes": included_types,
            "maxResultCount": 20,
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": latitude,
                        "longitude": longitude
                    },
                    "radius": radius
                }
            }
        }

        try:
            response = requests.post(self.url, headers=self.headers, json=payload)
            response.raise_for_status()
            data = response.json()
            results.extend(data.get('places', []))

            for _ in range(2):  # Fetch up to 2 more pages
                next_page_token = data.get('nextPageToken')
                if not next_page_token:
                    break
                time.sleep(2)  # Required delay before nextPageToken becomes valid
                payload["pageToken"] = next_page_token
                response = requests.post(self.url, headers= self.headers, json=payload)
                response.raise_for_status()
                data = response.json()
                results.extend(data.get('places', []))

        except requests.exceptions.RequestException as e:
            print(f"{Fore.RED}Request Error during pagination: {e}{Style.RESET_ALL}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"{Fore.RED}Error response: {e.response.text}{Style.RESET_ALL}")
            return []

        return results

    def _flatten_dict(self, d, parent_key='', sep='_'):
        """Flattens a nested dictionary into a single-level dictionary."""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            elif isinstance(v, list):
                if v and isinstance(v, list) and (len(v) > 0 and isinstance(v[-1], dict)):
                    items.append((new_key, json.dumps(v)))
                else:
                    items.append((new_key, ', '.join(map(str, v))))
            else:
                items.append((new_key, v))
        return dict(items)

    '''def save_to_csv(self, data, filename):
        """Saves the retrieved place data to a CSV file."""
        if not data:
            print(f"{Fore.YELLOW}No data to save.{Style.RESET_ALL}")
            return

        flattened_data = [self._flatten_dict(place) for place in data]
        keys = set().union(*(d.keys() for d in flattened_data))

        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=keys)
            writer.writeheader()
            for row in flattened_data:
                writer.writerow(row)

        print(f"{Fore.GREEN}Data saved to {filename}{Style.RESET_ALL}")'''
    
    def save_to_csv(self, data, filename):
        """Saves the retrieved place data to a CSV file using Pandas."""
        if not data:
            print(f"{Fore.YELLOW}No data to save.{Style.RESET_ALL}")
            return
        
        flattened_data = [self._flatten_dict(place) for place in data]
        # Convert list of dictionaries to DataFrame
        df = pd.DataFrame(flattened_data)
        # Save to CSV with UTF-8 encoding to handle multilingual text
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"{Fore.GREEN}Data saved to {filename}{Style.RESET_ALL}")


    def search_accommodations(self, sw_lat, sw_lon, ne_lat, ne_lon, included_types, rect_label=""):
        """
        Searches for accommodations within a specified rectangular area, subdividing if necessary
        to respect the radius limit and potentially capture more top results in dense areas.
        """
        max_allowed_radius_km = 49  # Be a bit conservative
        max_results_per_area = 20  # The API limit

        width = self.haversine_distance(sw_lat, sw_lon, sw_lat, ne_lon)
        height = self.haversine_distance(sw_lat, sw_lon, ne_lat, sw_lon)
        approx_diagonal = math.sqrt(width**2 + height**2)
        approx_radius = approx_diagonal / 2

        if approx_radius > max_allowed_radius_km:
            print(f"Rectangle {rect_label} (approx. radius {approx_radius:.2f} km) is too large. Subdividing for radius.")
            sub_rectangles = self.subdivide_rectangle(sw_lat, sw_lon, ne_lat, ne_lon, 2)
            all_sub_results = []
            for i, sub_rect in enumerate(sub_rectangles):
                sub_label = f"{rect_label}.{i+1}" if rect_label else str(i+1)
                results = self.search_accommodations(*sub_rect, included_types, sub_label)
                all_sub_results.extend(results)
            return all_sub_results
        else:
            center_lat, center_lon, _ = self.get_rectangle_center_and_radius(sw_lat, sw_lon, ne_lat, ne_lon)
            search_radius = min(approx_radius * 1.1 * 1000, max_allowed_radius_km * 1000)

            print(f"Searching within rectangle {rect_label} (center: {center_lat:.6f}, {center_lon:.6f}, radius: {search_radius:.2f} m)")
            results = self._get_all_pages_results(center_lat, center_lon, search_radius, included_types)
            results_count = len(results)
            print(f"Found {results_count} places in rectangle {rect_label}")
            self.search_area.add_rectangle(((sw_lat, sw_lon, ne_lat, ne_lon)), results_count, False)

            if results_count == max_results_per_area:
                print(f"Maximum results reached in dense area {rect_label}. Subdividing further to get all results.")
                sub_rectangles = self.subdivide_rectangle(sw_lat, sw_lon, ne_lat, ne_lon, 2)
                all_sub_results = list(results)  # Start with the initial results
                for i, sub_rect in enumerate(sub_rectangles):
                    sub_label = f"{rect_label}.{chr(ord('a') + i)}"
                    sub_results = self.search_accommodations(*sub_rect, included_types, sub_label)
                    all_sub_results.extend(sub_results)
                return all_sub_results
            else:
                return results

    def remove_duplicates_by_id(self, all_result_list):
        """Remove duplicates based on 'id' key while maintaining order."""
        return list({d['id']: d for d in reversed(all_result_list)}.values())[::-1]


    def create_map(self, initial_coords, map_filename):
        sw_lat, sw_lon, ne_lat, ne_lon = initial_coords
        center_lat = (sw_lat + ne_lat) / 2
        center_lon = (sw_lon + ne_lon) / 2

        m = folium.Map(location=[center_lat, center_lon], zoom_start=8) # Adjust zoom start as needed

        colormap = cm.LinearColormap(
            colors=['green', 'yellow', 'red'],
            vmin=0,
            vmax=60,
            caption='Number of results found'
        )
        m.add_child(colormap)

        for rect_coords, results_count, was_subdivided in self.search_area.rectangles:
            sw_lat, sw_lon, ne_lat, ne_lon = rect_coords
            bounds = [[sw_lat, sw_lon], [ne_lat, ne_lon]]

            color = colormap(results_count) if results_count > 0 else 'gray'

            folium.Rectangle(
                bounds=bounds,
                color=color,
                fill=True,
                weight=1,
                opacity=0.5,
                fill_opacity=0.2,
                popup=f"Results: {results_count}<br>{'Subdivided' if was_subdivided else 'Not subdivided'}",
            ).add_to(m)
        m.save(map_filename)
        print(f"\n{Fore.GREEN}Map saved as: {map_filename}{Style.RESET_ALL}")


    def search_places(self, sw_lat, sw_lon, ne_lat, ne_lon, included_types, filename= "places.csv", map_filename= "map.html", divisions=3):
        """
        Performs a comprehensive search for places within a given area, subdividing the area
        into smaller rectangles and saving results to a CSV file.
        """
        initial_coords = (sw_lat, sw_lon, ne_lat, ne_lon)
        print("Starting comprehensive search...")
        initial_rectangles = self.subdivide_rectangle(sw_lat, sw_lon, ne_lat, ne_lon, divisions)
        all_results = []
        self.search_area = SearchArea() # Reset search area for a new search

        for i, rect in enumerate(initial_rectangles, 1):
            print(f"\nSearching initial rectangle {i}")
            results = self.search_accommodations(*rect, included_types=included_types, rect_label=str(i))
            all_results.extend(results)

        print(f"\nTotal places found (before removing duplicates): {len(all_results)}")
        all_results = self.remove_duplicates_by_id(all_results)
        print(f"\nTotal places found (after removing duplicates): {len(all_results)}")

        if filename:
            self.save_to_csv(all_results, filename)

        if map_filename:
            self.create_map(initial_coords, map_filename)

        return all_results
// "Use my location" for the sample plan: picks the nearest sample city in the browser.
// The coordinates are compared with the city list on this page and never sent anywhere.
(function () {
  "use strict";

  function announce(message) {
    var live = document.getElementById("live");
    if (live) {
      live.textContent = message;
    }
  }

  // Great-circle distance in kilometres.
  function distanceKm(lat1, lon1, lat2, lon2) {
    var rad = Math.PI / 180;
    var dLat = (lat2 - lat1) * rad;
    var dLon = (lon2 - lon1) * rad;
    var a =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }

  function nearestOption(select, lat, lon) {
    var best = null;
    var bestDistance = Infinity;
    Array.prototype.forEach.call(select.options, function (option) {
      var d = distanceKm(lat, lon, Number(option.dataset.lat), Number(option.dataset.lon));
      if (d < bestDistance) {
        best = option;
        bestDistance = d;
      }
    });
    return best;
  }

  document.addEventListener("click", function (evt) {
    var button = evt.target.closest ? evt.target.closest("[data-action='nearest-city']") : null;
    if (!button) {
      return;
    }
    var select = document.getElementById(button.dataset.target);
    if (!select || !navigator.geolocation) {
      announce("This browser cannot share a location. Pick a city from the list instead.");
      return;
    }
    announce("Finding the nearest city in this browser.");
    navigator.geolocation.getCurrentPosition(
      function (position) {
        var option = nearestOption(select, position.coords.latitude, position.coords.longitude);
        if (option) {
          select.value = option.value;
          announce("Nearest sample city: " + option.textContent + ". Your location was not sent anywhere.");
        }
      },
      function () {
        announce("Location was not shared. Pick a city from the list instead.");
      },
      { maximumAge: 600000, timeout: 10000 }
    );
  });
})();

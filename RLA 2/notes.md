"We use a two-step process. First, geocoding converts plain addresses into GPS coordinates by querying the OpenStreetMap database through the OpenRouteService API — the client just types an address, no coordinates needed. Second, we send all coordinates to the ORS Matrix API in a single call, which runs Dijkstra's shortest-path algorithm on the real Paris road network to calculate driving distances and travel times between every pair of locations. This gives us a complete distance matrix that the routing algorithm then uses to plan deliveries."




1. All CRITICAL stops → sorted by earliest deadline
2. All HIGH stops     → sorted by earliest deadline  
3. All NORMAL stops   → Clarke-Wright + 2-opt (distance optimization)

No exceptions. No "but they're on the same street".

"Critical deliveries first"     critical = [i for i in stop_indices 
                                    if locations[i]["priority"] == "critical"]
                                # separated and locked at front

"Then high priority"            high = [i for i in stop_indices 
                                    if locations[i]["priority"] == "high"]
                                # locked after critical

"Then normal"                   normal = [i for i in stop_indices 
                                    if locations[i]["priority"] == "normal"]
                                # goes to Clarke-Wright + 2-opt

"within each priority level,    critical.sort(key=lambda i: (
choose nearest or most              time_window[0],   # earliest first
efficient order"                    time_window[1]))  # tightest deadline tiebreaker
                                # same for high

"Distance helps optimize        normal_routed = clarke_wright(normal, distances)
but never overrides priority"   normal_routed = two_opt(normal_routed, distances)
                                # distance optimization ONLY on normal stops

"Final order"                   final_route = critical + high + normal_routed
                                # priority first, distance second




constraints :

hospital delivery constraint (9am)
A->B->C (C due time is before A)
break constraint 

working in routing(2).py


-- osm2pgsql flex output for myTrack tracking_roadsegment (PostGIS).
-- Usage: see README.md in this directory.

local roads = osm.define_table({
    name = "tracking_roadsegment",
    ids = { type = "way", id_column = "osm_way_id" },
    columns = {
        { column = "geom", type = "linestring", projection = 4326, not_null = true },
        { column = "highway", type = "text" },
        { column = "maxspeed", type = "text" },
    },
})

function osm.process_way(object)
    if object.tags.highway then
        local g = object:as_linestring()
        if g then
            roads:insert({
                geom = g,
                highway = object.tags.highway,
                maxspeed = object.tags.maxspeed,
            })
        end
    end
end

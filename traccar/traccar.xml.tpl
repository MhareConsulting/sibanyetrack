<?xml version='1.0' encoding='UTF-8'?>

<!DOCTYPE properties SYSTEM 'http://java.sun.com/dtd/properties.dtd'>

<properties>

  <!-- Database: embedded H2 (swap for Postgres in prod) -->
  <entry key='database.driver'>org.h2.Driver</entry>
  <entry key='database.url'>jdbc:h2:/opt/traccar/data/database</entry>
  <entry key='database.user'>sa</entry>
  <entry key='database.password'></entry>

  <entry key='forward.enable'>true</entry>
  <entry key='forward.url'>http://web:8001/api/ingest/traccar/?token=${INGEST_API_TOKEN}&amp;org_slug=my-fleet&amp;deviceName={name}&amp;uniqueId={uniqueId}&amp;latitude={latitude}&amp;longitude={longitude}&amp;speed={speed}&amp;course={course}&amp;fixTime={fixTime}&amp;alarm={alarm}</entry>

  <!-- Web UI -->
  <entry key='web.origin'>*</entry>

</properties>


import xml.etree.ElementTree as ET



xml_data = '''

    <user>
    <id>1</id>

   <first_name>mich</first_name>
    
<age>30</age>

<email>ma.dats@yandex.ru</email>
       
    </user>
   
'''

root = ET.fromstring(xml_data)

print("User ID:", root.find('id').text)
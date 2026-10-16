(define (problem example_problem)
  (:domain robot3)
  (:objects
    robot1 robot2 robot3
    Watch_1 KeyChain_1
    Drawer_1 Drawer_2
    SideTable_1 SideTable_2 SideTable_3
    ArmChair_1 ArmChair_2
    Book_1 Bowl_1 Box_1
    Chair_1 Chair_2 Chair_3 Chair_4 Chair_5 Chair_6
    CoffeeTable_1
    CreditCard_1
    DeskLamp_1
    DiningTable_1
    FloorLamp_1
    GarbageCan_1
    HousePlant_1
    Laptop_1
    LightSwitch_1
    Newspaper_1
    Painting_1
    Pen_1 Pencil_1
    Pillow_1
    Plate_1
    RemoteControl_1
    Shelf_1 Shelf_2 Shelf_3
    Sofa_1
    Statue_1
    Television_1
    TissueBox_1
    TVStand_1
    Vase_1
    Window_1 Window_2
    location_130 location_229 location_230 location_136 location_164 location_57 location_230 location_195 location_99 location_77 location_23 location_189 location_93 location_193 location_233 location_160 location_232 location_213 location_75 location_78 location_150 location_124 location_70 location_47 location_232 location_181 location_191 location_167 location_232 location_173 location_226
  )
  (:init
    (at robot1 location_0)
    (at robot2 location_0)
    (at robot3 location_0)
    (on Watch_1 SideTable_3)
    (on KeyChain_1 SideTable_1)
    (has_location ArmChair_1 location_130)
    (has_location ArmChair_2 location_229)
    (has_location Book_1 location_230)
    (has_location Bowl_1 location_136)
    (has_location Box_1 location_164)
    (has_location Chair_1 location_57)
    (has_location Chair_2 location_230)
    (has_location Chair_3 location_195)
    (has_location Chair_4 location_99)
    (has_location Chair_5 location_77)
    (has_location Chair_6 location_23)
    (has_location CoffeeTable_1 location_189)
    (has_location CreditCard_1 location_93)
    (has_location DeskLamp_1 location_193)
    (has_location DiningTable_1 location_233)
    (has_location Drawer_1 location_160)
    (has_location Drawer_2 location_232)
    (has_location Floor_1 location_213)
    (has_location FloorLamp_1 location_213)
    (has_location GarbageCan_1 location_75)
    (has_location HousePlant_1 location_78)
    (has_location KeyChain_1 location_150)
    (has_location Laptop_1 location_124)
    (has_location LightSwitch_1 location_70)
    (has_location Newspaper_1 location_47)
    (has_location Painting_1 location_232)
    (has_location Pen_1 location_23)
    (has_location Pencil_1 location_57)
    (has_location Pillow_1 location_107)
    (has_location Plate_1 location_57)
    (has_location RemoteControl_1 location_78)
    (has_location Shelf_1 location_189)
    (has_location Shelf_2 location_191)
    (has_location Shelf_3 location_189)
    (has_location SideTable_1 location_160)
    (has_location SideTable_2 location_78)
    (has_location SideTable_3 location_232)
    (has_location Sofa_1 location_136)
    (has_location Statue_1 location_231)
    (has_location Television_1 location_202)
    (has_location TissueBox_1 location_181)
    (has_location TVStand_1 location_191)
    (has_location Vase_1 location_167)
    (has_location Watch_1 location_232)
    (has_location Window_1 location_173)
    (has_location Window_2 location_226)
    (at-location Watch_1 SideTable_3)
    (at-location KeyChain_1 SideTable_1)
    (openable Watch_1)
    (pickupable Watch_1)
    (openable KeyChain_1)
    (pickupable KeyChain_1)
    (openable Drawer_1)
    (pickupable Drawer_1)
    (openable Drawer_2)
    (pickupable Drawer_2)
  )
  (:goal
    (and
      (at-location Watch_1 Drawer_1)
      (at-location KeyChain_1 Drawer_1)
    )
  )
)
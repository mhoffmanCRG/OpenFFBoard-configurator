from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtWidgets import QDialog
from PyQt6.QtWidgets import QWidget
from PyQt6.QtWidgets import QMessageBox,QVBoxLayout,QCheckBox,QButtonGroup 
from PyQt6 import uic
from helper import res_path,classlistToIds
from PyQt6.QtCore import QTimer,QSettings
import main
from base_ui import WidgetUI
from base_ui import CommunicationHandler

class PwmDriverUI(WidgetUI,CommunicationHandler):
    
    def __init__(self, main=None, unique=0):
        WidgetUI.__init__(self, main,'pwmdriver_ui.ui')
        CommunicationHandler.__init__(self)
        self.main = main #type: main.MainUi
        self.instance = unique # pwmdrv instance. Multi axis boards have one PWM driver per axis
        
        self.pushButton_apply.clicked.connect(self.apply)

        self.register_callback("pwmdrv","freq",self.freq_cb,self.instance,str,typechar='!')
        self.register_callback("pwmdrv","freq",self.comboBox_freq.setCurrentIndex,self.instance,int,typechar='?')

        self.register_callback("pwmdrv","mode",self.pwmmode_cb,self.instance,str,typechar='!')
        self.register_callback("pwmdrv","mode",self.mode_value_cb,self.instance,int,typechar='?')
        self.register_callback("pwmdrv","dir",self.checkBox_invert.setChecked,self.instance,int,typechar='?')
        self.register_callback("pwmdrv","minduty",lambda v : self.doubleSpinBox_minduty.setValue(v/10),self.instance,int,typechar='?')
        self.register_callback("pwmdrv","autozero",self.checkBox_autozero.setChecked,self.instance,int,typechar='?')
        self.pushButton_autozero.clicked.connect(lambda : self.send_value("pwmdrv","calibrate",1,instance=self.instance))

        # Live output info
        self.register_callback("pwmdrv","active",lambda v : self.label_active.setText("Enabled" if v else "Disabled"),self.instance,int)
        self.register_callback("pwmdrv","torque",self.torque_cb,self.instance,int)
        self.register_callback("pwmdrv","duty",self.duty_cb,self.instance,int)
        self.register_callback("pwmdrv","hz",self.hz_cb,self.instance,int)
        self.duty = None
        self.zero = None
        self.hz = None

        # AASD servo helper. Values are only stored on this PC
        self.settings = QSettings("OpenFFBoard","Configurator")
        try:
            self.doubleSpinBox_dacfs.setValue(float(self.settings.value("pwmdrv/dacfs",3.3)))
            self.spinBox_pn189.setValue(int(self.settings.value("pwmdrv/pn189",100)))
        except (TypeError,ValueError):
            pass
        self.doubleSpinBox_dacfs.valueChanged.connect(self.aasd_changed)
        self.spinBox_pn189.valueChanged.connect(self.aasd_changed)
        self.label_aasd.setText(self.AASD_HELP)
        self.label_aasd.setMinimumHeight(self.label_aasd.heightForWidth(450)) # Wrapped rich text is not in the size hint
        self.update_aasd()
        self.register_callback("pwmdrv","zero",self.zero_cb,self.instance,int)
        self.register_callback("pwmdrv","calstate",self.calstate_cb,self.instance,int)
        self.calstate = 0
        self.calfail = 0
        self.calduty = 0
        self.caltravel = 0
        self.calstartv = 0
        # Diagnostics arrive before calstate in update_info so calstate_cb can show them
        self.register_callback("pwmdrv","calfail",lambda v : setattr(self,"calfail",v),self.instance,int)
        self.register_callback("pwmdrv","calduty",lambda v : setattr(self,"calduty",v),self.instance,int)
        self.register_callback("pwmdrv","caltravel",lambda v : setattr(self,"caltravel",v),self.instance,int)
        self.register_callback("pwmdrv","calstartv",lambda v : setattr(self,"calstartv",v),self.instance,int)
        self.calhigh = 0
        self.callow = 0
        self.register_callback("pwmdrv","calhigh",lambda v : setattr(self,"calhigh",v),self.instance,int)
        self.register_callback("pwmdrv","callow",lambda v : setattr(self,"callow",v),self.instance,int)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_info)

        self.init_ui()

    # Tab is currently shown
    def showEvent(self,event):
        self.update_info()
        self.timer.start(250)

    # Tab is hidden
    def hideEvent(self,event):
        self.timer.stop()

    def update_info(self):
        self.send_commands("pwmdrv",["active","torque","duty","hz","calfail","calduty","calhigh","callow","caltravel","calstartv","calstate","zero"],self.instance)

    CALSTATES = ["Not run (using zero torque duty)","Running... let go of the wheel","OK","Failed (using zero torque duty)"]
    CALFAILS = ["","Not in PWM/DIR mode","No encoder","Motor stopped (e-stop)",
                "No forward movement up to 25% duty (servo drive off?)","Wheel turned more than 3 turns",
                "Still turning at 25% duty","No backward movement down to minimum duty"]
    def calstate_cb(self,v):
        self.calstate = v
        text = self.CALSTATES[v] if 0 <= v < len(self.CALSTATES) else str(v)
        if v == 3: # Failed
            reason = self.CALFAILS[self.calfail] if 0 < self.calfail < len(self.CALFAILS) else f"Reason {self.calfail}"
            text += f"\n{reason}"
        if v in (2,3):
            label = "Zero" if v == 2 else "End duty"
            text += f"\n{label} {self.calduty/100:.2f} %"
            if self.calhigh:
                text += f" (forward from {self.calhigh/100:.2f} %"
                text += f", backward below {self.callow/100:.2f} %)" if self.callow else ")"
            text += f"\nMoved {self.caltravel} counts, start speed {self.calstartv} counts/100ms"
        self.label_calstate.setText(text)

    def zero_cb(self,v):
        source = "auto" if self.calstate == 2 else "manual"
        self.label_zero.setText(f"{v/100:.2f} % ({source})")
        self.zero = v
        self.update_aasd()

    def duty_cb(self,v):
        self.label_duty.setText(f"{v/100:.2f} %")
        self.duty = v
        self.update_aasd()

    def hz_cb(self,v):
        text = f"{v} Hz"
        if v > 6250:
            text += " (too fast for the LTC2644 PWM DAC, max 6.25 kHz: use 3 kHz)"
        self.label_hz.setText(text)
        self.hz = v

    AASD_HELP = (
        "<p><b>Recommended drive parameters</b> (save with Fn001):</p>"
        "<table cellspacing='0' cellpadding='2'>"
        "<tr><td><b>Pn002</b></td><td>0</td><td>Torque mode</td></tr>"
        "<tr><td><b>Pn053</b></td><td>18</td><td>SigIn2 (pin 7) = torque direction (CINV), from the PWM DIR output</td></tr>"
        "<tr><td><b>Pn188</b></td><td>10</td><td>Analog torque input filter (higher = smoother, more lag)</td></tr>"
        "<tr><td><b>Pn189</b></td><td>see above</td><td>Analog torque gain in % rated torque per volt</td></tr>"
        "<tr><td><b>Pn190</b></td><td>zero point</td><td>Analog torque offset in mV. Set with the output idle "
        "(Fn007 or adjust) so the free wheel stays still at the zero point Vref</td></tr>"
        "<tr><td><b>Pn198</b></td><td>500</td><td>Speed limit in torque mode (rpm). A free wheel with any offset runs up to this</td></tr>"
        "<tr><td><b>Pn051</b></td><td>1500</td><td>MMOS seller's recommended value</td></tr>"
        "<tr><td><b>dn-16</b></td><td></td><td>Monitor: analog torque voltage the drive sees. Should match <i>Vref now</i></td></tr>"
        "<tr><td><b>Fn007</b></td><td>run</td><td>Analog auto zero: sets Pn190 from the current Vref. "
        "Output enabled, torque 0 %, wheel free</td></tr>"
        "<tr><td><b>Fn001</b></td><td>run</td><td>Save parameters. Do it after Fn007 or any Pn change, else lost at power off</td></tr>"
        "</table>"
    )

    def aasd_changed(self,_=None):
        self.settings.setValue("pwmdrv/dacfs",self.doubleSpinBox_dacfs.value())
        self.settings.setValue("pwmdrv/pn189",self.spinBox_pn189.value())
        self.update_aasd()

    def update_aasd(self):
        fs = self.doubleSpinBox_dacfs.value()
        gain = self.spinBox_pn189.value()
        if self.duty is not None:
            self.label_vref.setText(f"{self.duty/10000*fs*1000:.0f} mV (compare with dn-16)")
        if self.zero is not None:
            mv = self.zero/10000*fs*1000
            self.label_vzero.setText(f"{mv:.0f} mV ({mv*gain/1000:.1f} % torque if not offset by Pn190)")
        self.label_fulltorque.setText(f"{fs:.2f} V x {gain} %/V = {fs*gain:.0f} % rated torque "
                                      f"(drive limit applies). Pn189 = {round(100/fs)} gives 100 % at full PWM")

    def torque_cb(self,v):
        direction = "positive" if v >= 0 else "negative"
        self.label_torque.setText(f"{v*100/32767:+.1f} % ({direction})")

    def init_ui(self):
        # Fill menus
        self.send_command("pwmdrv","freq",self.instance,'!')
        self.send_command("pwmdrv","mode",self.instance,'!')
        self.send_command("pwmdrv","dir",self.instance,'?')
        self.send_command("pwmdrv","minduty",self.instance,'?')
        self.send_command("pwmdrv","autozero",self.instance,'?')

    def freq_cb(self,modes):
        self.comboBox_freq.clear()
        modes = [m.split(":") for m in modes.split("\n") if m]
        for m in modes:
            self.comboBox_freq.addItem(m[0],m[1])
        self.send_command("pwmdrv","freq",self.instance,'?')

    def pwmmode_cb(self,modes):
        self.comboBox_mode.clear()
        modes = [m.split(":") for m in modes.split("\n") if m]
        for m in modes:
            self.comboBox_mode.addItem(m[0],m[1])
        self.send_command("pwmdrv","mode",self.instance,'?')

    def mode_value_cb(self,mode):
        """Selects the entry of a mode value. Multi axis boards only list some modes, so index != value"""
        for i in range(self.comboBox_mode.count()):
            if int(self.comboBox_mode.itemData(i)) == mode:
                self.comboBox_mode.setCurrentIndex(i)
                return

 
    def apply(self):
        self.send_value("pwmdrv","mode",self.comboBox_mode.currentData(),instance=self.instance)
        self.send_value("pwmdrv","freq",self.comboBox_freq.currentData(),instance=self.instance)
        self.send_value("pwmdrv","dir",1 if self.checkBox_invert.isChecked() else 0,instance=self.instance)
        self.send_value("pwmdrv","minduty",round(self.doubleSpinBox_minduty.value()*10),instance=self.instance)
        self.send_value("pwmdrv","autozero",1 if self.checkBox_autozero.isChecked() else 0,instance=self.instance)
        self.init_ui() # Update UI


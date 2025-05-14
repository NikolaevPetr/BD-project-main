from flask import Flask, render_template, request, session, redirect, url_for ,jsonify,flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import JSONB  
import logging ,hashlib
from sqlalchemy import  or_ ,func , cast ,asc  
from flask_migrate import Migrate
from urllib.parse import urlparse
import usb.core
import usb.util
from hashlib import sha256
from flask_login import LoginManager, login_user, current_user, login_required,UserMixin,logout_user
from werkzeug.utils import secure_filename
import os

app = Flask(__name__)
app.secret_key = 'FOLOM'

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:Fav2171186689@localhost/print_shop'

db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class PrintWarehouse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image = db.Column(db.String(255), nullable=False) 
    quantity = db.Column(db.Integer, default=0)   

    def __repr__(self):
        return f"<PrintWarehouse {self.image} - Quantity: {self.quantity}>"

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    model = db.Column(db.String(255))
    color = db.Column(db.String(255))
    size = db.Column(db.String(255))
    print_data = db.Column(JSONB)
    client_name = db.Column(db.String(255))
    notification_method = db.Column(db.String(255))
    client_contact = db.Column(db.String(255))
    promo_code = db.Column(db.String(255))
    status = db.Column(db.String(255))
    front_image = db.Column(db.Text)   
    back_image = db.Column(db.Text)
    issuance_manager = db.Column(db.String(255))
    reception_manager = db.Column(db.String(255))
    performer = db.Column(db.String(255))
    printer = db.Column(db.String(255))

class Products(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255),unique=True, nullable=False)
    image = db.Column(db.Text)
    is_sold_out = db.Column(db.Boolean, default=False)

class ProductModel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    name = db.Column(db.String(255))
    image = db.Column(db.Text)
    back_image = db.Column(db.Text)
    is_sold_out = db.Column(db.Boolean, default=False)

    sizes = db.relationship('Size', back_populates='product_model')

class Size(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_model_id = db.Column(db.Integer, db.ForeignKey('product_model.id'), nullable=False)
    size_name = db.Column(db.String(50))
    remaining_quantity = db.Column(db.Integer, default=0)

    product_model = db.relationship('ProductModel', back_populates='sizes')
    
class Employee(db.Model ,UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20), nullable=False, unique=True)
    password = db.Column(db.String(64), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    orders_completed = db.Column(db.Integer, default =0)
    working_hours = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(255))

@app.before_request
def create_tables():
    db.create_all() 

def get_model_image(model_name):
    model = ProductModel.query.filter_by(name=model_name).first()
    return model.image_path

def get_model_image_back(model_name):
    model = ProductModel.query.filter_by(name=model_name).first()
    return model.image_path_back

def get_orders_by_search_query(search_query, status=None):
    query = Order.query.filter(
        or_(
            Order.client_name.ilike(f'%{search_query}%'),
            Order.client_contact.ilike(f'%{search_query}%'),
            cast(Order.id, db.String).ilike(f'%{search_query}%')
        )
    )

    if status:
        query = query.filter_by(status=status)

    return query.all()

def convert_url_to_path(url):
    parsed_url = urlparse(url)
    return parsed_url.path

def move_to_print_warehouse(order):
    # Проверяем наличие данных о принте или тексте на заказе
    print_name = order.print_data.get('print')
    custom_text_name = order.print_data.get('customText')
    
    if print_name:
        converted_print_name = convert_url_to_path(print_name)
        print_exists = PrintWarehouse.query.filter_by(image=converted_print_name).first()
        if print_exists.quantity == 0:
            order.status = 'printing' 
        else:
            order.status = 'print'
            print_exists.quantity -= 1

            if custom_text_name:
                order.status = 'printing'
    else:
        if custom_text_name:
            order.status = 'printing'
        else:
            order.status = 'issue'

@app.route('/', methods=['GET', 'POST'])
def select_product():
    if request.method == 'POST':
        selected_product_id = request.form.get('selected_product')
        models_for_selected_product = ProductModel.query.filter_by(product_id=selected_product_id).all()
        return render_template('select_model.html', selected_product_id=selected_product_id, available_models=models_for_selected_product)

    # Получаем список продуктов
    available_products = Products.query.all()

    # Проверяем каждый продукт
    for product in available_products:

        # Проверяем, есть ли у продукта модели с количеством не равным нулю
        has_available_models = ProductModel.query.filter_by(product_id=product.id).join(Size).filter(Size.remaining_quantity > 0).count() > 0

        # Если есть, то добавляем информацию о том, что товар в наличии
        product.is_sold_out = not has_available_models

    return render_template('select_product.html', available_products=available_products)    

@app.route('/select_model', methods=['GET', 'POST'])
def select_model():
    selected_product = request.form.get('selected_product')
    session['selected_product'] = selected_product
    selected_product_instance = Products.query.filter_by(name=selected_product).first()
    models_for_selected_product = ProductModel.query.filter_by(product_id=selected_product_instance.id).all()

    # Проверяем размеры для каждой модели
    for model in models_for_selected_product:
        available_sizes_query = (
            Size.query
            .filter_by(product_model_id=model.id)
            .filter(Size.remaining_quantity > 0)
        )

        # Если есть хотя бы один размер с количеством больше нуля, то модель доступна
        has_available_sizes = available_sizes_query.count() > 0
        model.is_sold_out = not has_available_sizes

    return render_template('select_model.html', selected_product=selected_product, available_models=models_for_selected_product)


@app.route('/customize_product', methods=['POST', 'GET'])
def customize_product():
    selected_model_name = request.form.get('selected_model')
    selected_model = ProductModel.query.filter_by(name=selected_model_name).first()

    if not selected_model:
        # Обработка случая, если модель не найдена
        return render_template('error_page.html', error_message='Selected model not found.')

    session['selected_model'] = selected_model_name
   # Используйте этот запрос для получения размеров
    available_sizes_for_model = [size.size_name for size in Size.query.filter(Size.product_model == selected_model, Size.remaining_quantity > 0).all()]
    selected_model_image = selected_model.image
    back_model_image = selected_model.back_image

    return render_template('customize_product.html', selected_model_name=selected_model_name, selected_model_image=selected_model_image,
                           available_sizes=available_sizes_for_model, back_model_image=back_model_image)

@app.route('/select_print', methods=['POST'])
def select_print():
    selected_product = session.get('selected_product')
    selected_model = session.get('selected_model')
     

    if request.method == 'POST':
        selected_sizes_string = request.form.get('selected_size')
        modified_image_top = request.form.get('modified_image_top')
        modified_image_back = request.form.get('modified_image_back')
        selected_print = request.form.get('selected_print')
    
    available_prints = PrintWarehouse.query.all()

    return render_template('select_print.html', selected_product=selected_product, selected_model=selected_model,
                            selected_size=selected_sizes_string,
                            selected_print=selected_print, available_prints=available_prints,
                            selected_model_image=modified_image_top, back_model_image=modified_image_back)
    
@app.route('/final_step', methods=['POST', 'GET'])
def final_step():
    last_order = db.session.query(func.max(Order.id)).scalar()

    if last_order is None:
        order_id = 1
    else:
        order_id = last_order + 1
    if request.method == 'POST' :
        try:
            data = request.json

            # Извлекаем данные из запроса
            model = data.get('model')
            size = data.get('size')
            color = data.get('color')
            front_image = data.get('front_image')
            back_image = data.get('back_image')
            print_data = data.get('printData')
            client_name = data.get('client_name')
            client_contact = data.get('client_contact')
            notification_method = data.get('notification_method')
            promo_code = data.get('promo_code')

            # Создаем объект заказа
            order = Order(
                id = order_id,
                model=model,
                size=size,
                color=color,
                print_data=print_data,
                front_image = front_image,
                back_image = back_image,
                client_name=client_name,
                client_contact=client_contact,  
                notification_method=notification_method,
                promo_code=promo_code,
                status = "confirmation",
                performer = None,
                printer = None,
                issuance_manager = None,
                reception_manager = None

            )

            # Добавляем заказ в базу данных
            db.session.add(order)
            db.session.commit()

            logging.debug("Order successfully saved to the database - POST")
            
            # Отправляем ответ клиенту
            return jsonify({'message': 'Order successfully confirmed'})

        except Exception as e:
            logging.error("Error saving the order to the database - POST: %s", str(e))
            db.session.rollback()

            # Отправляем ответ с ошибкой клиенту
            return jsonify({'error': 'Failed to process the order'}), 500

    return render_template('final_step.html',order_id = order_id)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.')
    return redirect(url_for('login'))

@login_manager.user_loader
def load_user(user_id):
    user = Employee.query.get(int(user_id))
    return user

@app.route('/login', methods=['GET', 'POST'])
def login():
    __builtins__.print("Логин: метод запроса -", request.method)

    if current_user.is_authenticated:
        __builtins__.print("Текущий пользователь уже аутентифицирован:", current_user)
        return redirect(url_for(current_user.role))

    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        password = request.form.get('password')
        role = request.form.get('employeeRole')

        employee = Employee.query.filter_by(phone=phone).first()
        if employee:
            session['employee_phone'] = phone
            session['employee_name'] = name
            # Создаем хэш пароля с помощью SHA-256
            hashed_password = hashlib.sha256(password.encode()).hexdigest()

            if hashed_password == employee.password and employee.role == role:
                login_user(employee)
                __builtins__.print("Аутентификация успешна, перенаправление...")
                return redirect(url_for(role))
            else:
                flash('Invalid credentials or role mismatch', 'error')
                __builtins__.print("Неверные учетные данные или несоответствие роли")
        else:
            __builtins__.print("Сотрудник не найден")

    return render_template('login.html')



@app.route('/update_working_hours', methods=['POST'])
def update_working_hours():
    try:
        data = request.json
        elapsed_seconds = data.get('elapsedSeconds', 0)

        # Получаем номер телефона из сессии
        phone_from_session = session.get('employee_phone')

        # Получаем текущего сотрудника по номеру телефона
        current_employee = Employee.query.filter_by(phone=phone_from_session).first()

        if current_employee:
            # Обновление времени работы сотрудника в базе данных
            current_employee.working_hours += elapsed_seconds/3600.0
            db.session.commit()

            return jsonify({'message': 'Working hours updated successfully'})
        else:
            return jsonify({'error': 'Employee not found'}), 404

    except Exception as e:
        return jsonify({'error': 'Failed to update working hours'}), 500

@app.route('/reception', methods=['GET'])
@login_required
def reception():
    if current_user.role != 'reception':
        __builtins__.print("Роль пользователя не соответствует: перенаправление на логин")
        return redirect(url_for('login'))

    orders = Order.query.filter_by(status='confirmation').order_by(Order.id).all()
    return render_template('reception.html', orders=orders)

@app.route('/reception/search', methods=['POST'])
def reception_search():
    phone_from_session = session.get('employee_phone')
    employee = Employee.query.filter_by(phone = phone_from_session).first()
    if employee.status != 'pause':
        search_query = request.form.get('search_query')
        orders = get_orders_by_search_query(search_query)
        return render_template('reception.html', orders=orders)
    else:
        flash('Your work has been suspended by the administrator', 'error')
        return redirect(url_for('reception'))

@app.route('/reception_confirm/<int:order_id>', methods=['POST'])
def reception_confirm(order_id):
    # Confirm the order with the given order_id
    order = Order.query.get(order_id)
    employee_name = session.get('employee_name')
    employee_phone = session.get('employee_phone')
    employee = Employee.query.filter_by(phone = employee_phone).first()
    if employee.status != 'pause':
        if order:
            move_to_print_warehouse(order)

            # Transform the model name by adding underscores
            model_name = '_'.join(order.model.split())

            order.reception_manager = employee_name

            # Check if the order has a valid size
            if order.size:
                # Find the corresponding model by name
                selected_model = ProductModel.query.filter_by(name=model_name).first()

                # Check if the model exists
                if selected_model:
                    # Find the size in the model's sizes
                    selected_size = next((size for size in selected_model.sizes if size.size_name == order.size), None)

                    # Check if the size exists
                    if selected_size:
                        # Decrease the remaining quantity of the selected size
                        selected_size.remaining_quantity -= 1

                        # Update the model's sold_out status based on remaining quantities
                        selected_model.is_sold_out = all(size.remaining_quantity == 0 for size in selected_model.sizes)

                        current_employee = Employee.query.filter_by(phone=employee_phone).first()
                        
                        if current_employee:
                            current_employee.orders_completed += 1

                        # print a sheet with order information
                        db.session.commit()

                        print_to_printer(order)
                        return jsonify({'message': f'Order {order_id} successfully confirmed'})
                    else:
                        return jsonify({'error': f'Size {order.size} not found for model {model_name}'}), 404
                else:
                    return jsonify({'error': f'Model {model_name} not found'}), 404
            else:
                return jsonify({'error': f'Order {order_id} does not have a valid size'}), 400
        else:
            return jsonify({'error': f'Order {order_id} not found'}), 404
    else:
         return jsonify({'error': 'Your work has been suspended by the administrator'}), 400


@app.route('/reception_cancel/<int:order_id>', methods=['POST'])
def reception_cancel(order_id):
    # Cancel the order with the given order_id
    order = Order.query.get(order_id)
    employee_phone = session.get('employee_phone')
    employee = Employee.query.filter_by(phone=employee_phone).first()

    if employee.status != 'pause':
        if order:
            order.status = 'Canceled'
            order.reception_manager = employee.name if employee else None

            if employee:
                employee.orders_completed += 1
                db.session.commit()

            return jsonify({'message': f'Order {order_id} successfully canceled'})
        else:
            return jsonify({'error': f'Order {order_id} not found'}), 404
    else:
        return jsonify({'error': 'Your work has been suspended by the administrator'}), 403  # Использование кода 403 для обозначения запрета доступа

    
class UsbPrinter:
    def __init__(self, vid, pid, interface):
        self.vid = vid
        self.pid = pid
        self.interface = interface
        self.dev = None
        # Инициализация USB-подключения
        self.connected = self.connect()
        

    def connect(self):
        # Подключение к USB-устройству с использованием VID и PID
        self.dev = usb.core.find(idVendor=self.vid, idProduct=self.pid)

        if self.dev is None:
            raise Exception("Device not found. Make sure the printer is connected and VID/PID are specified correctly.")

        # Установка конфигурации и интерфейса
        self.dev.set_configuration()
        usb.util.claim_interface(self.dev, self.interface)

    def disconnect(self):
        # Отключение от USB-устройства
        if self.dev is not None:
            usb.util.release_interface(self.dev, self.interface)
            self.dev = None

    def text(self, text):
        # Отправка текста на принтер
        if self.dev is not None:
            try:
                # Преобразование текста в байты
                text_bytes = text.encode('utf-8')

                # Отправка байтов на принтер
                self.dev.write(self.interface, text_bytes)

                print("Text successfully sent to the printer.")
            except Exception as e:
                print(f"Error sending text to the printer: {str(e)}")

def print_to_printer(data):
    try:
        # Replace VID and PID with values for your printer
        VID = 0x03F0  # Vendor ID for HP
        PID = 0x012A  # Product ID for your printer

        # Initialize connection to the printer using new VID and PID
        printer = UsbPrinter(VID, PID, 1)  # Assuming that the interface is 1
        # Sending data to the printer
        printer.text("Model: {}\n".format(data['model']))
        printer.text("Color: {}\n".format(data['color']))
        printer.text("Size: {}\n".format(data['size']))
        printer.text("Client Name: {}\n".format(data['client_name']))
        printer.text("Notification Method: {}\n".format(data['notification_method']))
        printer.text("Client Contact: {}\n".format(data['client_contact']))
        printer.text("Promo Code: {}\n".format(data['promo_code']))
        # Add other data you want to print

        return {'message': 'Data successfully sent to the printer'}
    except Exception as e:
        return {'error': str(e)}

@app.route('/printing', methods=['GET'])
@login_required
def printing():
    # Проверяем, что текущий пользователь имеет роль 'printing'
    if current_user.role != 'printing':
        # Если роль пользователя не 'printing', перенаправляем на страницу логина или другую подходящую страницу
        return redirect(url_for('login'))

    orders = Order.query.filter_by(status='printing', performer=None).order_by(Order.id).all()
    orders_in_progress = Order.query.filter_by(status='printing', performer=current_user.name).order_by(Order.id).all()

    return render_template('printing.html', orders=orders, orders_in_progress=orders_in_progress, employee_name=current_user.name, employee_phone=current_user.phone)

@app.route('/get_task', methods=['POST'])
def get_task():
    if request.method == 'POST':
        order_id = request.form.get('order_id')
        employee_name = request.form.get('employee_name')
        employee_phone = request.form.get('employee_phone')
        
        employee = Employee.query.filter_by(name=employee_name, phone=employee_phone).first()
        if employee is None or employee.status == 'pause':
             flash('Your work has been suspended by the administrator', 'error')
             return redirect(url_for('printing'))

        if not order_id:
            order = Order.query.filter_by(status='printing', performer=None).order_by(asc(Order.id)).first()
        else:
            order = Order.query.filter_by(id=order_id, status='printing', performer=None).first()
            if not order:
                return render_template('no_task.html')

        if 'print' in order.print_data:
            print_url = order.print_data['print']
            # Разбиваем URL на части и берем последнюю часть
            print_name = print_url.split('/')[-1]
            # Формируем путь к файлу
            file_path = '/static/prints/' + print_name

            print_exists = PrintWarehouse.query.filter_by(image=file_path).first()

            if print_exists and print_exists.quantity == 0:
                order.performer = employee_name
                db.session.commit()
                task_data = {
                    'order_id': order.id,
                    'model': order.model,
                    'size': order.size,
                    'print_data': order.print_data,
                    'front_image': order.front_image,
                    'back_image': order.back_image,
                    'performer': order.performer
                }
                return render_template('get_task.html', task_data=task_data)
            elif not print_exists or print_exists.quantity > 0:
                order.performer = employee_name
                db.session.commit()
                task_data = {
                    'order_id': order.id,
                    'model': order.model,
                    'size': order.size,
                    'print_data': {'customText': order.print_data.get('customText', '')},
                    'front_image': order.front_image,
                    'back_image': order.back_image,
                    'performer': order.performer
                }
                return render_template('get_task.html', task_data=task_data)
        else:
            order.performer = employee_name
            db.session.commit()
            task_data = {
                'order_id': order.id,
                'model': order.model,
                'size': order.size,
                'print_data': order.print_data,
                'front_image': order.front_image,
                'back_image': order.back_image,
                'performer': order.performer
            }
            return render_template('get_task.html', task_data=task_data)

    return jsonify({'error': 'Invalid request method'}), 405

@app.route('/complete_task/<int:order_id>', methods=['POST'])
def complete_task(order_id):
    order = Order.query.get(order_id)
    employee_phone = session.get('employee_phone')

    # Получение информации о сотруднике
    current_employee = Employee.query.filter_by(phone=employee_phone).first()

    # Проверка статуса сотрудника
    if current_employee and current_employee.status == 'pause':
        # Возвращаем ошибку, если сотрудник на паузе
        flash('Your work has been suspended by the administrator', 'error')
        return redirect(url_for('printing'))
         

    if order and order.status == 'printing':
        order.status = 'print'

        if current_employee:
            current_employee.orders_completed += 1

        db.session.commit()

        return redirect(url_for('printing'))
    else:
        return jsonify({'error': 'Order status must be "printing" to complete'}), 400


@app.route('/continue_order', methods=['POST'])
def continue_order():
    if request.method == 'POST':
         
        order_id = request.form.get('order_id')
        employee_name = request.form.get('employee_name')
        employee_phone = request.form.get('employee_phone')
        
        employee = Employee.query.filter_by(name=employee_name, phone=employee_phone).first()
        if employee is None or employee.status == 'pause':
             flash('Your work has been suspended by the administrator', 'error')
             return redirect(url_for('printing'))
            
        if employee_name and order_id:
            order = Order.query.filter_by(id=order_id, performer = employee_name).first()

            if order:
                # Определяем, какие данные отправлять в зависимости от наличия принта на складе
                if 'print' in order.print_data:
                    print_url = order.print_data['print']
                    # Разбиваем URL на части и берем последнюю часть
                    print_name = print_url.split('/')[-1]
                    # Формируем путь к файлу
                    file_path = '/static/prints/' + print_name

                    print_exists = PrintWarehouse.query.filter_by(image=file_path).first()

                    if print_exists and print_exists.quantity == 0:
                        
                        # Принт существует, отправляем только customText
                        task_data = {
                            'order_id': order.id,
                            'model': order.model,
                            'size': order.size,
                            'print_data': order.print_data,
                            'front_image': order.front_image,
                            'back_image': order.back_image,
                            'performer': order.performer
                        }

                    else:
                        # Принта нет, отправляем все данные
                        task_data = {
                            'order_id': order.id,
                            'model': order.model,
                            'size': order.size,
                            'print_data': {'customText': order.print_data.get('customText')},
                            'front_image': order.front_image,
                            'back_image': order.back_image,
                            'performer': order.performer
                        }

                    return render_template('get_task.html', task_data=task_data)
                else:
                    # Принта нет, отправляем все данные
                    task_data = {
                        'order_id': order.id,
                        'model': order.model,
                        'size': order.size,
                        'print_data': order.print_data,
                        'front_image': order.front_image,
                        'back_image': order.back_image,
                        'performer': order.performer
                    }

                    return render_template('continue_order.html', task_data=task_data)
            else:
                return render_template('no_task.html')

        else:
            return render_template('no_task.html')

    return jsonify({'error': 'Invalid request method'}), 405

@app.route('/print', methods=['GET'])
@login_required
def print():
    # Проверяем, что текущий пользователь имеет роль 'print'
    if current_user.role != 'print':
        return redirect(url_for('login'))

    orders = Order.query.filter_by(status='print', printer=None).order_by(Order.id).all()
    orders_in_progress = Order.query.filter_by(status='print', printer=current_user.name).order_by(Order.id).all()

    return render_template('print.html', orders=orders, orders_in_progress=orders_in_progress,
                           employee_name=current_user.name, employee_phone=current_user.phone)

@app.route('/print_task', methods=['POST'])
def print_task():
    if request.method == 'POST':

        order_id = request.form.get('order_id')  # Добавлено получение номера заказа
        employee_name = request.form.get('employee_name')
        employee_phone = request.form.get('employee_phone')
        
        employee = Employee.query.filter_by(name=employee_name, phone=employee_phone).first()
        if employee is None or employee.status == 'pause':
             flash('Your work has been suspended by the administrator', 'error')
             return redirect(url_for('print'))

        # Если order_id не указан, выбираем заказ с минимальным ID
        if not order_id:
            order = Order.query.filter_by(status='print', printer=None).order_by(asc(Order.id)).first()
        else:
            # Поиск заказа по указанному номеру
            order = Order.query.filter_by(id=order_id, status='print', printer=None).first()
            # Проверка наличия order
            if not order:
                # Если order не найден, вызываем no_task
                return render_template('no_task.html')
            
        if order:
            order.printer = employee_name
            db.session.commit()

            task_data = {
                'order_id': order.id,
                'print_data': order.print_data,
                'front_image': order.front_image,
                'back_image': order.back_image
            }

            return render_template('print_task.html', task_data=task_data)

        return jsonify({'error': 'Invalid order or status for printing'}), 400

    return jsonify({'error': 'Invalid data'}), 400


@app.route('/continue_print_task', methods=['POST'])
def continue_print_task():
    if request.method == 'POST':
  
        order_id = request.form.get('order_id')
        employee_name = request.form.get('employee_name')
        employee_phone = request.form.get('employee_phone')
        
        employee = Employee.query.filter_by(name=employee_name, phone=employee_phone).first()
        if employee is None or employee.status == 'pause':
             flash('Your work has been suspended by the administrator', 'error')
             return redirect(url_for('print'))

        if employee_name and order_id:
            order = Order.query.filter_by(id=order_id, printer= employee_name).first()

            if order:
                order.printer = employee_name
                db.session.commit()

                task_data = {
                    'order_id': order.id,
                    'print_data': order.print_data,
                    'front_image': order.front_image,
                    'back_image': order.back_image
                }

                return render_template('continue_print_task.html', task_data=task_data)

            return render_template('no_task.html')

        return render_template('no_task.html')


@app.route('/complete_print_task/<int:order_id>', methods=['POST'])
def complete_print_task(order_id):
    # Находим заказ с указанным ID
    order = Order.query.get(order_id)
    employee_phone = session.get('employee_phone')

     # Получение информации о сотруднике
    current_employee = Employee.query.filter_by(phone=employee_phone).first()

    # Проверка статуса сотрудника
    if current_employee and current_employee.status == 'pause':
        # Возвращаем ошибку, если сотрудник на паузе
        flash('Your work has been suspended by the administrator', 'error')
        return redirect(url_for('print'))

    if order and order.status == 'print':
        # Обновление статуса заказа на 'issue'
        order.status = 'issue'

        current_employee = Employee.query.filter_by(phone=employee_phone).first()
        if current_employee:
            current_employee.orders_completed += 1

        db.session.commit()

        # Перенаправление на страницу интерфейса МАСТЕРА ПЕЧАТИ
        return redirect(url_for('print'))

    # Если статус заказа не соответствует ожидаемому, возвращаем ошибку
    return jsonify({'error': 'Order status must be "print" to complete'}), 400


@app.route('/issue', methods=['GET', 'POST'])
@login_required
def issue():
    # Проверяем, что текущий пользователь имеет роль 'issue'
    if current_user.role != 'issue':
        return redirect(url_for('login'))

    # Получаем все заказы со статусом 'issue' из базы данных
    orders = Order.query.filter_by(status='issue').order_by(Order.id).all()
    return render_template('issue.html', orders=orders)

@app.route('/issue/search', methods=['POST'])
def issue_search():
    search_query = request.form.get('search_query')
    phone_from_session = session.get('employee_phone')
    employee = Employee.query.filter_by(phone = phone_from_session).first()
    if employee.status != 'pause':
        orders = get_orders_by_search_query(search_query, status='issue')
        return render_template('issue.html', orders=orders)
    else:
        flash('Your work has been suspended by the administrator', 'error')
        return redirect(url_for('issue'))

@app.route('/issue_order/<int:order_id>', methods=['POST' ,'GET'])
def issue_order(order_id):
    order = Order.query.get(order_id)
    employee_name = session.get('employee_name')
    employee_phone = session.get('employee_phone')
    employee = Employee.query.filter_by(phone = employee_phone).first()
    if employee.status != 'pause':

        if order:
            order.status = 'Completed' 
            order.issuance_manager = employee_name

            current_employee = Employee.query.filter_by(phone = employee_phone).first()
            if current_employee:
                current_employee.orders_completed += 1

            db.session.commit()

            return jsonify({'message': f'Order {order_id} successfully issued'})
        else:
            return jsonify({'error': f'Order {order_id} not found'}), 404
    else:
         return jsonify({'error': 'Your work has been suspended by the administrator'}), 400
    
    
@app.route('/dashboard')
def dashboard():
    # Retrieve orders with the status 'issue' and 'ПОДТВЕРЖДЕНИЕ', 'НАНЕСЕНИЕ', 'ПЕЧАТЬ' from the database
    ready_orders = Order.query.filter_by(status='issue').order_by(Order.id).all()
    processing_orders = Order.query.filter(Order.status.in_(['confirmation', 'printing', 'print'])).order_by(Order.id).all()
    return render_template('dashboard.html', ready_orders=ready_orders, processing_orders=processing_orders)

@app.route('/administrator')
@login_required
def administrator():
    if current_user.role != 'administrator':
        return redirect(url_for('login'))

    return render_template('administrator.html')

@app.route('/upload_background_image', methods=['POST'])
@login_required
def upload_background_image():
    save_directory = os.path.join(app.root_path, 'static', 'background_image')

    # Создание папки, если она не существует
    if not os.path.exists(save_directory):
        os.makedirs(save_directory)

    save_path = os.path.join(save_directory, 'background.jpg')

    if 'backgroundImage' in request.files and request.files['backgroundImage'].filename != '':
        file = request.files['backgroundImage']
        file.save(save_path)
        return jsonify({'message': 'File uploaded successfully'}), 200
    else:
        # Удалить существующий файл фона, если выбран дефолтный фон
        if os.path.exists(save_path):
            os.remove(save_path)
        return jsonify({'message': 'Default background set successfully'}), 200

    
@app.route('/get_background_data')
def get_background_data():
    saved_image_path = os.path.join(app.root_path, 'static', 'background_image', 'background.jpg')

    if os.path.exists(saved_image_path):
        url_for_saved_image = url_for('static', filename='background_image/background.jpg')
        return jsonify({'backgroundImage': url_for_saved_image})
    else:
        return jsonify({'backgroundColor': 'linear-gradient(to right, #ffb6c1, #63a69f)'})


@app.route('/reset_orders', methods=['POST'])
def reset_orders():
    try:
        # Удаляем все заказы из базы данных
        Order.query.delete()
        db.session.commit()

        # Возвращаем успешный ответ
        return jsonify({'success': True}), 200
    except Exception as e:
        # Если произошла ошибка, возвращаем ошибку
        return jsonify({'error': str(e)}), 500
    

@app.route('/fetch_orders', methods=['GET'])
def fetch_orders():
    try:
        orders = Order.query.order_by(Order.id).all()

        # Преобразование объектов заказов в словари для сериализации в JSON
        orders_data = []
        for order in orders:
            order_data = {
                'id': order.id,
                'client_name': order.client_name,
                'client_contact': order.client_contact,
                'model': order.model,
                'size': order.size,
                'color': order.color,
                'notification_method': order.notification_method,
                'promo_code': order.promo_code,
                'performer': order.performer,
                'printer': order.printer,
                'status': order.status
            }
            orders_data.append(order_data)

        return jsonify(orders_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    

def get_order_by_search_query(search_query):
    query = Order.query.filter(
        or_(
            Order.client_name.ilike(f'%{search_query}%'),
            Order.client_contact.ilike(f'%{search_query}%'),
            cast(Order.id, db.String).ilike(f'%{search_query}%'),
            Order.model.ilike(f'%{search_query}%'),
            Order.size.ilike(f'%{search_query}%'),
            Order.color.ilike(f'%{search_query}%'),
            Order.notification_method.ilike(f'%{search_query}%'),
            Order.promo_code.ilike(f'%{search_query}%'),
            Order.performer.ilike(f'%{search_query}%'),
            Order.printer.ilike(f'%{search_query}%'),
            Order.status.ilike(f'%{search_query}%')
        )
    )
    return query.order_by(Order.id).all()()

# Маршрут для вызова функции по URL
@app.route('/search_orders')
def search_orders():
    search_query = request.args.get('search_query', '')
    orders = get_order_by_search_query(search_query)
    # Преобразование результатов в формат JSON и возврат
    orders_data = [{'id': order.id, 'client_name': order.client_name, 'client_contact': order.client_contact, 'model': order.model, 'size': order.size, 'color': order.color, 'notification_method': order.notification_method, 'promo_code': order.promo_code, 'performer': order.performer, 'printer': order.printer, 'status': order.status} for order in orders]
    return jsonify(orders_data)


@app.route('/change_order_status', methods=['POST'])
def change_order_status():
    try:
        data = request.json

        order_id = data['orderId']
        new_status = data['newStatus']

        order = Order.query.get(order_id)
        if not order:
            return jsonify({'error': f'Order with id {order_id} not found'}), 404

        # Обновление статуса заказа
        order.status = new_status
        db.session.commit()

        return jsonify({'message': 'Order status changed successfully'})
    except Exception as e:
        return jsonify({'error': f'An unexpected error occurred: {str(e)}'}), 500

@app.route('/delete_order', methods=['POST'])
def delete_order():
    data = request.json
    order_id = data.get('orderId')

    order = Order.query.get(order_id)
    if order:
        db.session.delete(order)
        db.session.commit()
        return jsonify({'message': 'Order deleted successfully'})
    else:
        return jsonify({'error': 'Order not found'}), 404
    
@app.route('/delete_all_orders', methods=['POST'])
def delete_all_orders():
    orders = Order.query.all()
    for order in orders:
        db.session.delete(order)
    db.session.commit()
    return jsonify({'message': 'All orders deleted successfully'})

@app.route('/add_order', methods=['POST'])
def add_order():
    try:
        data = request.json

        # Извлекаем данные из запроса
        client_name = data.get('clientName')
        client_contact = data.get('clientContact')
        model = data.get('model')
        size = data.get('size')
        color = data.get('color')
        notification_method = data.get('notificationMethod')
        promo_code = data.get('promoCode')
        performer = data.get('performer')
        printer = data.get('printer')
        issuance_manager = data.get('issuanceManager')
        reception_manager = data.get('receptionManager')
        status = data.get('status')
        front_image = data.get('front_image')
        back_image = data.get('back_image')
        print_data = data.get('print_data')

        # Создаем новый заказ в базе данных 
        new_order = Order(
            client_name=client_name,
            client_contact=client_contact,
            model=model,
            size=size,
            color=color,
            notification_method=notification_method,
            promo_code=promo_code,
            performer=performer,
            printer=printer,
            issuance_manager= issuance_manager,
            reception_manager =reception_manager,
            status=status,
            front_image=front_image,
            back_image=back_image,
            print_data=print_data
        )

        # Добавляем заказ в сессию и сохраняем изменения в базе данных
        db.session.add(new_order)
        db.session.commit()

        return jsonify({'message': 'Order added successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/add_product', methods=['POST'])
def add_product():
    try:
        data = request.json

        # Извлекаем данные из запроса
        product_name = data.get('productName')
        product_image_url = data.get('productImageURL')

        # Проверяем наличие записи в таблице Products
        existing_product = Products.query.filter_by(name=product_name).first()

        if existing_product:
            # Если запись существует, используем её product_id
            product_id = existing_product.id
        else:
            # Если записи нет, создаем новую
            new_product = Products(name=product_name, image=product_image_url)
            db.session.add(new_product)
            db.session.commit()
            # Получаем product_id после вставки новой записи
            product_id = new_product.id

        return jsonify({'message': 'Product added successfully', 'product_id': product_id})
    except Exception as e:
        # Логируем ошибку
        logging.error(f"Error adding product: {str(e)}")
        # Возвращаем более информативный JSON-ответ
        return jsonify({'error': 'Internal Server Error', 'details': str(e)}), 500
    
@app.route('/add_model', methods=['POST'])
def add_model():
    try:
        data = request.json

        # Извлекаем данные из запроса
        product_id_for_model = data.get('productIdForModel')
        model_name = data.get('modelName')
        model_image_url = data.get('modelImageURL')
        back_image_model_url = data.get('backImageModelURL')

        # Проверяем наличие записи в таблице Products
        existing_product = Products.query.get(product_id_for_model)

        if not existing_product:
            return jsonify({'error': 'Product not found'}), 404

        # Создаем новую запись в ProductModel
        new_model = ProductModel(
            product_id=product_id_for_model,
            name=model_name,
            image=model_image_url,
            back_image=back_image_model_url
        )
        db.session.add(new_model)
        db.session.commit()

        # Создаем размеры для новой модели
        sizes_to_create = [
            "S (48-50)",
            "M (52-54)",
            "L (56-58)",
            "XL (60-62)",
            "XXL (64-66)",
            "3XL (68-70)",
            "4XL (72-74)",
            "5XL (76-78)",
            "6XL (80-82)"
        ]

        for size_name in sizes_to_create:
            new_size = Size(
                product_model=new_model,
                size_name=size_name,
                remaining_quantity=0
            )
            db.session.add(new_size)

        db.session.commit()

        return jsonify({'message': 'Model added successfully'})
    except Exception as e:
        # Логируем ошибку
        logging.error(f"Error adding model: {str(e)}")
        # Возвращаем более информативный JSON-ответ
        return jsonify({'error': 'Internal Server Error', 'details': str(e)}), 500

@app.route('/delete_model', methods=['POST'])
def delete_model():
    try:
        data = request.json
        model_id = data.get('modelId')
        model = ProductModel.query.get(model_id)

        if model:
            # Удаляем связанные размеры
            related_sizes = Size.query.filter_by(product_model_id=model.id).all()
            for related_size in related_sizes:
                db.session.delete(related_size)

            # Удаляем саму модель
            db.session.delete(model)
            db.session.commit()

            logging.info(f"Model {model_id} and related sizes deleted successfully.")
            return jsonify({'message': 'Model and related sizes deleted successfully'})
        else:
            logging.warning(f"Attempted to delete non-existent model with id {model_id}.")
            return jsonify({'error': 'Model not found'}), 404
    except Exception as e:
        # Логируем ошибку
        logging.error(f"Error deleting model and related sizes: {str(e)}")
        # Возвращаем более информативный JSON-ответ
        return jsonify({'error': 'Internal Server Error', 'details': str(e)}), 500

# Функция для удаления всех моделей
@app.route('/delete_all_models', methods=['POST'])
def delete_all_models():
    try:
        models = ProductModel.query.all()

        for model in models:
            # Удаляем связанные размеры
            related_sizes = Size.query.filter_by(product_model_id=model.id).all()
            for related_size in related_sizes:
                db.session.delete(related_size)

            # Удаляем саму модель
            db.session.delete(model)

        db.session.commit()
        logging.info("All models and related sizes deleted successfully.")
        return jsonify({'message': 'All models and related sizes deleted successfully'})
    except Exception as e:
        # Логируем ошибку
        logging.error(f"Error deleting all models and related sizes: {str(e)}")
        # Возвращаем более информативный JSON-ответ
        return jsonify({'error': 'Internal Server Error', 'details': str(e)}), 500

@app.route('/delete_product', methods=['POST'])
def delete_product():
    try:
        data = request.json
        product_id = data.get('productId')

        product = Products.query.get(product_id)
        if product:
            # Удаляем связанные модели в таблице ProductModel
            related_models = ProductModel.query.filter_by(product_id=product.id).all()
            for related_model in related_models:
                # Удаляем связанные размеры
                related_sizes = Size.query.filter_by(product_model_id=related_model.id).all()
                for related_size in related_sizes:
                    db.session.delete(related_size)

                # Удаляем саму модель
                db.session.delete(related_model)

            # Удаляем сам продукт
            db.session.delete(product)
            db.session.commit()
            
            logging.info(f"Product {product_id} and related models and sizes deleted successfully.")
            return jsonify({'message': 'Product and related models and sizes deleted successfully'})
        else:
            logging.warning(f"Attempted to delete non-existent product with id {product_id}.")
            return jsonify({'error': 'Product not found'}), 404
    except Exception as e:
        # Логируем ошибку
        logging.error(f"Error deleting product and related models and sizes: {str(e)}")
        # Возвращаем более информативный JSON-ответ
        return jsonify({'error': 'Internal Server Error', 'details': str(e)}), 500

# Функция для удаления всех продукций и связанных моделей
@app.route('/delete_all_products', methods=['POST'])
def delete_all_products():
    try:
        products = ProductModel.query.all()

        for product in products:
            # Удаляем связанные модели
            related_models = Products.query.filter_by(product_id=product.id).all()
            for related_model in related_models:
                # Удаляем связанные размеры
                related_sizes = Size.query.filter_by(product_model_id=related_model.id).all()
                for related_size in related_sizes:
                    db.session.delete(related_size)

                # Удаляем саму модель
                db.session.delete(related_model)

            # Удаляем сам продукт
            db.session.delete(product)

        db.session.commit()
        logging.info("All products and associated models and sizes deleted successfully.")
        return jsonify({'message': 'All products and associated models and sizes deleted successfully'})
    except Exception as e:
        # Логируем ошибку
        logging.error(f"Error deleting all products and associated models and sizes: {str(e)}")
        # Возвращаем более информативный JSON-ответ
        return jsonify({'error': 'Internal Server Error', 'details': str(e)}), 500
    
@app.route('/modify_product_quantity', methods=['POST'])
def modify_product_quantity():
    product_id = request.json.get('productId')
    model_id = request.json.get('modelId')
    size_name = request.json.get('size')
    quantity_to_modify = request.json.get('quantity')

    product = Products.query.get(product_id)

    if product:
        model = ProductModel.query.get(model_id)

        if model:
            # Используем like для поиска по первой букве
            size = Size.query.filter(
                func.substr(func.regexp_replace(Size.size_name, '\([^)]*\)', ''), 1, 1) == size_name,
                Size.product_model_id == model_id
            ).first()

            if size:
                # Обновляем количество для указанного размера внутри указанной модели
                size.remaining_quantity = quantity_to_modify
                db.session.commit()

                return jsonify({'message': 'Product quantity modified successfully'}), 200

            return jsonify({'error': 'Size not found'}), 404

        return jsonify({'error': 'Model not found'}), 404

    return jsonify({'error': 'Product not found'}), 404
    
@app.route('/add_print', methods=['POST'])
def add_print():
    try:
        data = request.json
        image_url = data.get('printImageURL')

        # Проверка наличия URL изображения
        if not image_url:
            return jsonify({'error': 'Image URL is required'}), 400

        quantity = data.get('printQuantity', 0)

        new_print = PrintWarehouse(image=image_url, quantity=quantity)

        db.session.add(new_print)
        db.session.commit()

        logging.info(f"Print added successfully with image URL: {image_url}")
        return jsonify({'message': 'Print added successfully'})
    except Exception as e:
        # Логируем ошибку
        logging.error(f"Error adding print: {str(e)}")
        # Возвращаем более информативный JSON-ответ
        return jsonify({'error': 'Internal Server Error', 'details': str(e)}), 500

# Маршрут для удаления принта по ID
@app.route('/delete_print', methods=['POST'])
def delete_print():
    try:
        data = request.json
        print_id = data.get('printId')

        # Проверка наличия ID принта
        if not print_id:
            return jsonify({'error': 'Print ID is required'}), 400

        print_to_delete = PrintWarehouse.query.get(print_id)
        if print_to_delete:
            # Удаляем принт
            db.session.delete(print_to_delete)
            db.session.commit()
            
            logging.info(f"Print {print_id} deleted successfully.")
            return jsonify({'message': 'Print deleted successfully'})
        else:
            logging.warning(f"Attempted to delete non-existent print with id {print_id}.")
            return jsonify({'error': 'Print not found'}), 404
    except Exception as e:
        # Логируем ошибку
        logging.error(f"Error deleting print: {str(e)}")
        # Возвращаем более информативный JSON-ответ
        return jsonify({'error': 'Internal Server Error', 'details': str(e)}), 500

@app.route('/delete_all_prints', methods=['POST'])
def delete_all_prints():
    try:
        prints_to_delete = PrintWarehouse.query.all()

        # Проверка наличия принтов перед их удалением
        if not prints_to_delete:
            return jsonify({'message': 'No prints to delete'})

        for print_to_delete in prints_to_delete:
            db.session.delete(print_to_delete)

        db.session.commit()

        logging.info("All prints deleted successfully.")
        return jsonify({'message': 'All prints deleted successfully'})
    except Exception as e:
        # Логируем ошибку
        logging.error(f"Error deleting all prints: {str(e)}")
        # Возвращаем более информативный JSON-ответ
        return jsonify({'error': 'Internal Server Error', 'details': str(e)}), 500

# Маршрут для изменения оставшегося количества принта по ID

@app.route('/modify_print_quantity', methods=['POST'])
def modify_print_quantity():
    data = request.json
    print_id = data.get('printId')
    new_quantity = data.get('quantity')

    try:
        print_to_modify = PrintWarehouse.query.get(print_id)

        if print_to_modify:
            print_to_modify.quantity = new_quantity
            db.session.commit()
            return jsonify({'message': 'print quantity modified successfully'})
        else:
            return jsonify({'error': 'print not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/add_employee', methods=['POST'])
def add_employee():
    data = request.json
    name = data.get('name')
    phone = data.get('phone')
    password = data.get('password')
    role = data.get('role')
    try:
        hashed_password = sha256(password.encode()).hexdigest()
        new_employee = Employee(name=name, phone=phone, password=hashed_password, role=role)
        db.session.add(new_employee)
        db.session.commit()
        return jsonify({'message': 'Employee added successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/delete_employee', methods=['POST'])
def delete_employee():
    try:
        data = request.json
        employee_id = data.get('employee_id')
        
        employee_to_delete = Employee.query.get(employee_id)
        if employee_to_delete:
            db.session.delete(employee_to_delete)
            db.session.commit()
            return jsonify({'message': 'Employee deleted successfully'})
        else:
            return jsonify({'error': 'Employee not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/delete_all_employees', methods=['POST'])
def delete_all_employees():
    try:
        Employee.query.filter(Employee.role != 'administrator').delete()
        db.session.commit()
        return jsonify({'message': 'Non-admin employees deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    
@app.route('/pause_all_employees', methods=['POST'])
def pause_all_employees():
    try:
        # Получаем список всех работников, исключая работников со статусом "administrator"
        employees_to_pause = Employee.query.filter(Employee.role != 'administrator').all()
        # Устанавливаем статус "pause" для каждого работника
        for employee in employees_to_pause:
            employee.status = 'pause'

        db.session.commit()
        return jsonify({'message': 'All non-administrator employees set to "pause" status successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/update_status', methods=['POST'])
def update_status():
    try:
        # Обновляем статус на NULL для всех записей
        employees = Employee.query.all()
        for employee in employees:
            employee.status = None
        db.session.commit()
        return jsonify({'message': 'Status updated to NULL successfully for all employees'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    
@app.route('/delete_all_data', methods=['POST'])
def delete_all_data():
    try:
        # Удаление данных из каждой таблицы
        db.session.query(PrintWarehouse).delete()
        db.session.query(Order).delete()
        db.session.query(Products).delete()
        db.session.query(ProductModel).delete()
        db.session.query(Size).delete()
        db.session.query(Employee).delete()
        db.session.commit()
        return jsonify({'message': 'All data successfully deleted from all tables'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    
@app.route('/get_employee_status', methods=['GET'])
def get_employee_status():
    first_employee = Employee.query.first()

    if first_employee:
        employee_status = first_employee.status
        return jsonify({'status': employee_status})
    else:
        return jsonify({'status': 'unknown'}), 404  # Возвращаем "unknown" статус, если не удалось найти работника

@app.route('/get_orders_info', methods=['GET'])
def get_orders_info():
    try:
        total_orders = Order.query.count()
        processed_orders = Order.query.filter_by(status='confirmation').count()
        accepted_orders = Order.query.filter(Order.status.in_(['printing', 'print'])).count()
        manufactured_prints = Order.query.filter_by(status='print').count()
        printed_orders = Order.query.filter_by(status='issue').count()
        issued_orders = Order.query.filter_by(status='Completed').count()

        return jsonify({
            'total_orders': total_orders,
            'processed_orders': processed_orders,
            'accepted_orders': accepted_orders,
            'manufactured_prints': manufactured_prints,
            'printed_orders': printed_orders,
            'issued_orders': issued_orders
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/get_all_queues_info', methods=['GET'])
def get_all_queues_info():
    try:
        reception_queue_size = Order.query.filter_by(status='confirmation').count()  # Замените на вашу функцию для получения размера очереди ресепшна
        application_queue_size = Order.query.filter_by(status='printing', performer=None).count()  # Замените на вашу функцию для получения размера очереди заявок
        print_queue_size = Order.query.filter_by(status='print', printer=None).count()  # Замените на вашу функцию для получения размера очереди печати
        issue_queue_size = Order.query.filter_by(status='issue').count()  # Замените на вашу функцию для получения размера очереди выдачи

        return jsonify({
            'reception_queue_size': reception_queue_size,
            'application_queue_size': application_queue_size,
            'print_queue_size': print_queue_size,
            'issue_queue_size': issue_queue_size
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/calculate_metrics', methods=['GET'])
def calculate_metrics():
    try:
        roles = ['print', 'printing', 'issue', 'reception']

        employees_info = []

        for role in roles:
            # Получаем список сотрудников для каждой роли
            employees = Employee.query.filter_by(role=role).all()

            for employee in employees:
                # Для каждого сотрудника считаем items_per_hour и округляем до целого
                items_per_hour = round(employee.orders_completed / employee.working_hours) if employee.working_hours > 0 else 0

                # Собираем информацию о сотруднике
                employee_info = {
                    'name': employee.name,
                    'role': role,
                    'items_per_hour': items_per_hour
                }

                # Добавляем информацию в список
                employees_info.append(employee_info)

        return jsonify({'employees_info': employees_info})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

  
@app.route('/calculate_average_time_per_item', methods=['GET'])
def calculate_average_time_per_item():
    try:
        roles = ['print', 'printing', 'issue', 'reception']  # Замени на нужные роли

        total_hours = 0
        total_orders = 0

        for role in roles:
            employee_with_max_orders = Employee.query.filter_by(role=role).order_by(Employee.orders_completed.desc()).first()

            if employee_with_max_orders:
                total_hours += employee_with_max_orders.working_hours
                total_orders += employee_with_max_orders.orders_completed

        # Проверка для роли "issue"
        issuance_employee = Employee.query.filter_by(role='issue').first()
        if issuance_employee and issuance_employee.orders_completed == 0:
            average_time_per_item = 0
        else:
            average_time_per_item = round(total_hours / total_orders, 4) if total_orders > 0 else 0

        return jsonify({'average_time_per_item': average_time_per_item})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0' , port= 80 , debug=True)
    